"""In-memory SandboxClient fake shared across test modules."""
from groktimizer.core.sandbox import ExecResult, SandboxMeta


class FakeSandboxClient:
    def __init__(self):
        self.sandboxes: dict[str, SandboxMeta] = {}
        self.files: dict[tuple[str, str], str] = {}
        self.execs: list[tuple[str, str]] = []
        self.exec_responses: dict[str, ExecResult] = {}  # substring -> result

    async def create(self, name, image, region, labels, envs):
        self.sandboxes[name] = SandboxMeta(name=name, labels=dict(labels))

    async def delete(self, name):
        self.sandboxes.pop(name, None)

    async def list(self, labels):
        return [m for m in self.sandboxes.values()
                if all(m.labels.get(k) == v for k, v in labels.items())]

    async def exec(self, name, command, timeout_s=120):
        self.execs.append((name, command))
        for needle, result in self.exec_responses.items():
            if needle in command:
                return result
        return ExecResult(stdout="", exit_code=0)

    async def write_file(self, name, path, content):
        self.files[(name, path)] = content
