"""Observe and steer a subordinate agent through its sandbox exec channel."""

import json
import shlex
from datetime import UTC, datetime
from uuid import uuid4

from groktimizer.core.sandbox import SandboxClient

LOG = "/var/log/gtz/session.log"
CHAT_LOG = "/var/log/gtz/chat.jsonl"


async def agent_status(client: SandboxClient, name: str) -> dict:
    r = await client.exec(
        name,
        f"tmux has-session -t gtz 2>/dev/null && echo running; stat -c %Y {LOG} 2>/dev/null",
    )
    lines = r.stdout.split()
    running = "running" in lines
    mtimes = [tok for tok in lines if tok.isdigit()]
    return {"running": running, "log_mtime": int(mtimes[0]) if mtimes else None}


async def tail_log(client: SandboxClient, name: str, lines: int = 50) -> str:
    r = await client.exec(name, f"tail -n {int(lines)} {LOG}")
    return r.stdout


async def tail_messages(client: SandboxClient, name: str, lines: int = 80) -> list[dict[str, str]]:
    r = await client.exec(name, f"tail -n {int(lines)} {CHAT_LOG} 2>/dev/null || true")
    messages = []
    for line in r.stdout.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(message, dict)
            and isinstance(message.get("id"), str)
            and isinstance(message.get("body"), str)
            and isinstance(message.get("at"), str)
        ):
            role = message.get("role")
            messages.append(
                {
                    "id": message["id"],
                    "role": role if role in ("user", "agent") else "user",
                    "body": message["body"],
                    "at": message["at"],
                }
            )
    return messages


# Appends the resumed grok run's final response to chat.jsonl as a structured
# agent reply, so chat is two-way instead of steering-only. Runs in the sandbox.
_APPEND_REPLY_PY = (
    "import json,sys,uuid,datetime as dt\n"
    "body=open(sys.argv[1]).read().strip()\n"
    "rec={'id':'reply-'+uuid.uuid4().hex,'role':'agent','body':body,"
    "'at':dt.datetime.now(dt.timezone.utc).isoformat()}\n"
    f"body and open({CHAT_LOG!r},'a').write(json.dumps(rec)+chr(10))\n"
)


async def send_message(client: SandboxClient, name: str, message: str) -> str:
    """Steer an agent. Returns the chat message id of the steering record."""
    # Steering replaces the current headless turn, then resumes the same session from
    # the project clone. Keeping the process inside the named tmux session preserves
    # accurate liveness reporting for the CLI and web control plane. The run's stdout
    # is teed to the session log AND captured so the reply lands in chat.jsonl.
    script = (
        "{ . /opt/gtz/.env; } 2>/dev/null; "
        'export PATH="$HOME/.local/bin:$HOME/.grok/bin:$PATH"; '
        "export GIT_ASKPASS=/opt/gtz/git-askpass.sh GIT_TERMINAL_PROMPT=0; "
        "cd /workspace/project; "
        'reply_file=$(mktemp /tmp/gtz-reply.XXXXXX); '
        "grok --continue --always-approve "
        '${GTZ_GROK_MODEL:+--model "$GTZ_GROK_MODEL"} '
        '${GTZ_REASONING_EFFORT:+--reasoning-effort "$GTZ_REASONING_EFFORT"} '
        f'-p "$0" 2>&1 | tee -a {LOG} > "$reply_file"; '
        f'python3 -c {shlex.quote(_APPEND_REPLY_PY)} "$reply_file"; '
        'rm -f "$reply_file"'
    )
    resume = shlex.join(["bash", "-lc", script, message])
    message_id = f"steer-{uuid4().hex}"
    chat_event = json.dumps(
        {
            "id": message_id,
            "role": "user",
            "body": message,
            "at": datetime.now(UTC).isoformat(),
        },
        separators=(",", ":"),
    )
    command = (
        "tmux kill-session -t gtz 2>/dev/null || true; "
        f"printf '%s\\n' {shlex.quote(chat_event)} >> {CHAT_LOG}; "
        f"tmux new-session -d -s gtz {shlex.quote(resume)}"
    )
    await client.exec(name, command)
    return message_id


async def exec_in_agent(
    client: SandboxClient, name: str, command: str, timeout_s: int = 120
) -> str:
    r = await client.exec(name, command, timeout_s=timeout_s)
    return r.stdout
