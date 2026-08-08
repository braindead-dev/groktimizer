"""Observe and steer a subordinate agent through its sandbox exec channel."""
import shlex

from groktimizer.core.sandbox import SandboxClient

LOG = "/var/log/gtz/session.log"


async def agent_status(client: SandboxClient, name: str) -> dict:
    r = await client.exec(
        name, f"tmux has-session -t gtz 2>/dev/null && echo running; stat -c %Y {LOG} 2>/dev/null"
    )
    lines = r.stdout.split()
    running = "running" in lines
    mtimes = [tok for tok in lines if tok.isdigit()]
    return {"running": running, "log_mtime": int(mtimes[0]) if mtimes else None}


async def tail_log(client: SandboxClient, name: str, lines: int = 50) -> str:
    r = await client.exec(name, f"tail -n {int(lines)} {LOG}")
    return r.stdout


async def send_message(client: SandboxClient, name: str, message: str) -> None:
    quoted = shlex.quote(message)
    # --continue resumes the latest session for the cwd, so run from the project clone.
    script = (
        '{ . /opt/gtz/.env; } 2>/dev/null; '
        'export PATH="$HOME/.local/bin:$HOME/.grok/bin:$PATH"; cd /workspace/project; '
        f'nohup grok --continue --always-approve -p "$0" >> {LOG} 2>&1 &'
    )
    await client.exec(name, "bash -lc " + shlex.quote(script) + " " + quoted)


async def exec_in_agent(client: SandboxClient, name: str, command: str, timeout_s: int = 120) -> str:
    r = await client.exec(name, command, timeout_s=timeout_s)
    return r.stdout
