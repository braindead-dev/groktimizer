"""The one module that touches the Blaxel SDK. Everything else uses SandboxClient."""
from blaxel.core import SandboxInstance

from groktimizer.core.sandbox import ExecResult, SandboxMeta


class BlaxelSandboxClient:
    def __init__(self, region: str):
        self.region = region

    async def create(self, name, image, region, labels, envs):
        await SandboxInstance.create_if_not_exists({
            "name": name,
            "image": image,
            "memory": 4096,
            "region": region or self.region,
            "labels": labels,
            "envs": [{"name": k, "value": v} for k, v in envs.items()],
        })

    async def delete(self, name):
        await SandboxInstance.delete(name)

    async def list(self, labels):
        out = []
        page = await SandboxInstance.list()
        async for sb in page.auto_paging_iter():
            meta = sb.metadata
            raw = getattr(meta, "labels", None)
            sb_labels = dict(getattr(raw, "additional_properties", None) or raw or {})
            if all(sb_labels.get(k) == v for k, v in labels.items()):
                out.append(SandboxMeta(name=meta.name, labels=sb_labels))
        return out

    async def exec(self, name, command, timeout_s=120):
        sb = await SandboxInstance.get(name)
        r = await sb.process.exec({
            "command": command,
            "wait_for_completion": True,
            "timeout": timeout_s * 1000,
        })
        stdout = r.logs if isinstance(getattr(r, "logs", None), str) else None
        if stdout is None:
            stdout = getattr(r, "stdout", "") or ""
        exit_code = getattr(r, "exit_code", 0)
        return ExecResult(stdout=stdout, exit_code=exit_code if isinstance(exit_code, int) else 0)

    async def write_file(self, name, path, content):
        sb = await SandboxInstance.get(name)
        await sb.fs.write(path, content)
