"""Observe and steer a subordinate agent through its sandbox exec channel."""

import hashlib
import json
import shlex
from pathlib import Path
from uuid import uuid4

from groktimizer.config import Config
from groktimizer.core.sandbox import SandboxClient

RUNNER = "/opt/gtz/agent_runner.py"
RUNNER_LOG = "/var/log/gtz/runner.log"


def _runtime_config_env(cfg: Config) -> str:
    return "".join(
        f"export {key}={shlex.quote(value)}\n"
        for key, value in {
            "GTZ_CONFIG_JSON": cfg.model_dump_json(),
            "GTZ_TOOLING_REPO": cfg.tooling_repo,
            "GTZ_SHARED_REPO": cfg.shared_repo,
        }.items()
    )


def _quiesce_runner() -> str:
    """Stop the daemon and any detached Grok child before a runtime replacement."""
    return (
        f"python3 {RUNNER} shutdown >/dev/null 2>&1 || true; "
        "for attempt in 1 2 3 4 5 6 7 8 9 10; do "
        "tmux has-session -t gtz 2>/dev/null || break; sleep 0.2; done; "
        "tmux kill-session -t gtz 2>/dev/null || true; "
        "for signal in TERM KILL; do "
        "for proc_dir in /proc/[0-9]*; do "
        'test "$(cat "$proc_dir/comm" 2>/dev/null)" = grok || continue; '
        'kill -$signal "${proc_dir##*/}" 2>/dev/null || true; '
        "done; sleep 0.2; done; "
    )


def _last_json(stdout: str) -> dict | None:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


async def agent_status(client: SandboxClient, name: str) -> dict:
    r = await client.exec(
        name,
        f"tmux has-session -t gtz 2>/dev/null && echo running; "
        "test -f /opt/gtz/provisioning && echo provisioning; "
        "pgrep -f '[b]ash /opt/gtz/setup.sh' >/dev/null && echo provisioning; "
        f"python3 {RUNNER} status 2>/dev/null || true; "
        f"stat -c %Y {RUNNER_LOG} 2>/dev/null",
    )
    lines = r.stdout.split()
    running = "running" in lines
    provisioning = "provisioning" in lines
    mtimes = [tok for tok in lines if tok.isdigit()]
    runtime = _last_json(r.stdout) or {}
    return {
        "running": running,
        "provisioning": provisioning,
        "log_mtime": int(mtimes[-1]) if mtimes else None,
        "turn_status": runtime.get("turn_status", "idle" if running else "stopped"),
        "active_turn_id": runtime.get("active_turn_id"),
        "queued": runtime.get("queued", 0),
        "cursor": runtime.get("cursor", 0),
        "session_id": runtime.get("session_id"),
        "runtime_id": runtime.get("runtime_id"),
    }


async def tail_log(client: SandboxClient, name: str, lines: int = 50) -> str:
    r = await client.exec(
        name,
        f"tail -n {int(lines)} {RUNNER_LOG} 2>/dev/null || true",
    )
    return r.stdout


async def runtime_snapshot(client: SandboxClient, name: str, after: int = 0) -> dict | None:
    r = await client.exec(
        name,
        f"python3 {RUNNER} export --after {max(0, int(after))} 2>/dev/null || true",
    )
    return _last_json(r.stdout)


async def send_message(
    client: SandboxClient,
    name: str,
    message: str,
    *,
    mode: str = "queue",
    client_id: str | None = None,
    sender_kind: str = "operator",
    sender_sandbox: str | None = None,
    sender_label: str | None = None,
    retry: bool = False,
) -> dict:
    """Queue or interrupt with a steering turn in the sandbox-local runner."""
    if mode not in {"queue", "interrupt"}:
        raise ValueError("mode must be queue or interrupt")
    if not message.strip() or len(message) > 4_000:
        raise ValueError("message must contain 1-4,000 characters")
    client_id = client_id or f"client-{uuid4().hex}"
    turn_id = f"turn-{uuid4().hex}"
    args = [
        "python3",
        RUNNER,
        "enqueue",
        "--message",
        message,
        "--client-id",
        client_id,
        "--turn-id",
        turn_id,
        "--mode",
        mode,
        "--sender-kind",
        sender_kind,
    ]
    if sender_sandbox:
        args.extend(["--sender-sandbox", sender_sandbox])
    if sender_label:
        args.extend(["--sender-label", sender_label])
    if retry:
        args.append("--retry-existing")
    start_runner = (
        "tmux has-session -t gtz 2>/dev/null || "
        "tmux new-session -d -s gtz "
        + shlex.quote(
            "{ . /opt/gtz/.env; } 2>/dev/null; "
            "{ . /opt/gtz/config.env; } 2>/dev/null; "
            'export PATH="$HOME/.local/bin:$HOME/.grok/bin:$PATH"; '
            "export GIT_ASKPASS=/opt/gtz/git-askpass.sh GIT_TERMINAL_PROMPT=0; "
            "cd /workspace/project; "
            f"exec python3 {RUNNER} daemon >>{RUNNER_LOG} 2>&1"
        )
    )
    r = await client.exec(name, f"{start_runner}; {shlex.join(args)}")
    result = _last_json(r.stdout)
    if r.exit_code != 0 or not result:
        raise RuntimeError("agent turn runner is unavailable; repair the sandbox first")
    return result


async def interrupt_turn(client: SandboxClient, name: str) -> dict:
    """Stop the active generation without adding a replacement turn."""
    r = await client.exec(name, f"python3 {RUNNER} interrupt 2>/dev/null || true")
    result = _last_json(r.stdout)
    if r.exit_code != 0 or not result:
        raise RuntimeError("agent turn runner is unavailable; repair the sandbox first")
    return result


async def ensure_runtime_current(client: SandboxClient, name: str, cfg: Config) -> bool:
    """Refresh a durable runner only when its code or live config is stale."""
    runner_source = Path(__file__).with_name("agent_runner.py").read_text()
    config_env = _runtime_config_env(cfg)
    expected = {
        hashlib.sha256(runner_source.encode()).hexdigest(),
        hashlib.sha256(config_env.encode()).hexdigest(),
    }
    probe = await client.exec(
        name,
        f"sha256sum {RUNNER} /opt/gtz/config.env 2>/dev/null | cut -d' ' -f1",
    )
    actual = set(probe.stdout.split())
    if expected.issubset(actual):
        return False
    runtime = await runtime_snapshot(client, name)
    if not runtime or not runtime.get("runtime_id"):
        return False
    if runtime.get("turn_status") in {"running", "interrupting"}:
        return False
    await repair_runtime(client, name, cfg)
    return True


async def repair_runtime(client: SandboxClient, name: str, cfg: Config | None = None) -> dict:
    """Restart a current queued runner while preserving its recorded Grok session."""
    runtime = await runtime_snapshot(client, name)
    if cfg is not None:
        config_env = _runtime_config_env(cfg)
        await client.write_file(name, "/opt/gtz/config.env", config_env)
        await client.exec(name, "chmod 600 /opt/gtz/config.env")
    if not runtime or not runtime.get("runtime_id") or not runtime.get("session_id"):
        if cfg is None:
            raise RuntimeError("unsupported agent runner; bootstrap repair is required")
        legacy_session = await client.exec(
            name,
            'find "$HOME/.grok/sessions/%2Fworkspace%2Fproject" '
            "-mindepth 1 -maxdepth 1 -type d -printf '%T@ %f\\n' 2>/dev/null "
            "| sort -nr | head -n 1 | cut -d' ' -f2-",
        )
        session_id = legacy_session.stdout.strip() or str(uuid4())
        source = Path(__file__).with_name("agent_runner.py").read_text()
        await client.exec(name, "mkdir -p /opt/gtz /var/lib/gtz /var/log/gtz")
        await client.write_file(name, RUNNER, source)
        await client.write_file(
            name,
            "/opt/gtz/objective.md",
            "Resume the existing research assignment.",
        )
        overrides = {
            "GTZ_TOOLING_REPO": cfg.tooling_repo,
            "GTZ_SHARED_REPO": cfg.shared_repo,
            "GTZ_CONFIG_JSON": cfg.model_dump_json(),
            "GTZ_SESSION_ID": session_id,
        }
        exports = " ".join(
            f"export {key}={shlex.quote(value)};" for key, value in overrides.items()
        )
        init_args = ["python3", RUNNER, "init", "--session-id", session_id]
        if legacy_session.stdout.strip():
            init_args.append("--started")
        init = shlex.join(init_args)
        enqueue = shlex.join(
            [
                "python3",
                RUNNER,
                "enqueue",
                "--message-file",
                "/opt/gtz/brief.md",
                "--display-message-file",
                "/opt/gtz/objective.md",
                "--client-id",
                f"upgrade-{session_id}",
                "--turn-id",
                f"turn-upgrade-{session_id}",
                "--sender-kind",
                "system",
                "--sender-label",
                "Research brief",
            ]
        )
        start = _quiesce_runner() + (
            f"touch {RUNNER_LOG}; "
            "tmux new-session -d -s gtz "
            + shlex.quote(
                "{ . /opt/gtz/.env; } 2>/dev/null; "
                "{ . /opt/gtz/config.env; } 2>/dev/null; "
                'export PATH="$HOME/.local/bin:$HOME/.grok/bin:$PATH"; '
                "export GIT_ASKPASS=/opt/gtz/git-askpass.sh GIT_TERMINAL_PROMPT=0; "
                "cd /workspace/project; "
                f"exec python3 {RUNNER} daemon >>{RUNNER_LOG} 2>&1"
            )
        )
        repaired = await client.exec(
            name,
            f"{exports} {{ . /opt/gtz/.env; }} 2>/dev/null; "
            "{ . /opt/gtz/config.env; } 2>/dev/null; "
            'export PATH="$HOME/.local/bin:$HOME/.grok/bin:$PATH"; '
            f'chmod 700 {RUNNER}; pip install --quiet "git+${{GTZ_TOOLING_REPO}}"; '
            "grok mcp remove groktimizer >/dev/null 2>&1 || true; "
            "grok mcp add groktimizer -- python3 -m groktimizer.mcp; "
            f"{init}; {enqueue}; {start}",
            timeout_s=900,
        )
        if repaired.exit_code != 0:
            raise RuntimeError("failed to complete legacy agent bootstrap")
        runtime = await runtime_snapshot(client, name)
        if not runtime or not runtime.get("runtime_id") or not runtime.get("session_id"):
            raise RuntimeError("legacy agent bootstrap completed without a runner")
        return {
            "repaired": True,
            "session_id": str(runtime["session_id"]),
            "reinitialized": True,
        }
    source = Path(__file__).with_name("agent_runner.py").read_text()
    await client.exec(name, "mkdir -p /opt/gtz /var/lib/gtz /var/log/gtz")
    await client.write_file(name, RUNNER, source)
    session_id = str(runtime["session_id"])
    init = shlex.join(["python3", RUNNER, "init", "--session-id", session_id, "--started"])
    start = _quiesce_runner() + (
        f"if [ -s {RUNNER_LOG} ]; then mv {RUNNER_LOG} {RUNNER_LOG}.previous; fi; "
        f"touch {RUNNER_LOG}; : > {RUNNER_LOG}; "
        "tmux new-session -d -s gtz "
        + shlex.quote(
            "{ . /opt/gtz/.env; } 2>/dev/null; "
            "{ . /opt/gtz/config.env; } 2>/dev/null; "
            'export PATH="$HOME/.local/bin:$HOME/.grok/bin:$PATH"; '
            "export GIT_ASKPASS=/opt/gtz/git-askpass.sh GIT_TERMINAL_PROMPT=0; "
            "cd /workspace/project; "
            f"exec python3 {RUNNER} daemon >>{RUNNER_LOG} 2>&1"
        )
    )
    refresh = (
        "{ . /opt/gtz/.env; } 2>/dev/null; "
        "{ . /opt/gtz/config.env; } 2>/dev/null; "
        'export PATH="$HOME/.local/bin:$HOME/.grok/bin:$PATH"; '
        'pip install --quiet "git+${GTZ_TOOLING_REPO}"; '
        "grok mcp remove groktimizer >/dev/null 2>&1 || true; "
        "grok mcp add groktimizer -- python3 -m groktimizer.mcp; "
    )
    r = await client.exec(name, f"{refresh} chmod 700 {RUNNER}; {init}; {start}", timeout_s=900)
    if r.exit_code != 0:
        raise RuntimeError("failed to repair the agent turn runner")
    return {"repaired": True, "session_id": session_id, "reinitialized": False}


async def exec_in_agent(
    client: SandboxClient, name: str, command: str, timeout_s: int = 120
) -> str:
    r = await client.exec(name, command, timeout_s=timeout_s)
    return r.stdout
