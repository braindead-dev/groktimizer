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
            messages.append({key: message[key] for key in ("id", "body", "at")})
    return messages


async def send_message(client: SandboxClient, name: str, message: str) -> None:
    # Steering replaces the current headless turn, then resumes the same session from
    # the project clone. Keeping the process inside the named tmux session preserves
    # accurate liveness reporting for the CLI and web control plane.
    script = (
        "{ . /opt/gtz/.env; } 2>/dev/null; "
        'export PATH="$HOME/.local/bin:$HOME/.grok/bin:$PATH"; '
        "export GIT_ASKPASS=/opt/gtz/git-askpass.sh GIT_TERMINAL_PROMPT=0; "
        "cd /workspace/project; "
        "grok --continue --always-approve "
        '${GTZ_GROK_MODEL:+--model "$GTZ_GROK_MODEL"} '
        '${GTZ_REASONING_EFFORT:+--reasoning-effort "$GTZ_REASONING_EFFORT"} '
        f'-p "$0" >> {LOG} 2>&1'
    )
    resume = shlex.join(["bash", "-lc", script, message])
    chat_event = json.dumps(
        {
            "id": f"steer-{uuid4().hex}",
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


async def exec_in_agent(
    client: SandboxClient, name: str, command: str, timeout_s: int = 120
) -> str:
    r = await client.exec(name, command, timeout_s=timeout_s)
    return r.stdout
