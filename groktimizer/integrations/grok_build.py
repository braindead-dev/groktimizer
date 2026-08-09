"""Safely register the fastest Groktimizer endpoint as a Grok Build model."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

BEGIN_MARKER = "# >>> groktimizer fast model >>>"
END_MARKER = "# <<< groktimizer fast model <<<"
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
DEFAULT_BASE_URL = "https://xwdq0i6koerlhu-8000.proxy.runpod.net/v1"
DEFAULT_MODEL = "grok-2-fast"
DEFAULT_ALIAS = "groktimized-2"
DEFAULT_NAME = "Groktimized 2"
STANDARD_BASE_URL = "https://z08tqd2khleyx4-8000.proxy.runpod.net/v1"
STANDARD_MODEL = "grok-2"
STANDARD_ALIAS = "grok-2-normal"
STANDARD_NAME = "Grok 2"
LEGACY_ALIASES = ("groktimizer-fast",)
MANAGED_DESCRIPTION = "Accelerated Grok 2 deployment by Groktimizer"
STANDARD_MANAGED_DESCRIPTION = "Grok 2 deployment managed by Groktimizer"
MANAGED_DESCRIPTIONS = {
    MANAGED_DESCRIPTION,
    STANDARD_MANAGED_DESCRIPTION,
    "Standard Grok 2 deployment",
    "Optimized Grok 2 deployment by Groktimizer",
    "Optimized Grok deployment managed by Groktimizer",
}
TRUSTED_PUBLIC_ENDPOINTS = {DEFAULT_BASE_URL, STANDARD_BASE_URL}
ADVERTISED_MODEL_ALIASES = {DEFAULT_MODEL: {"grok-2-madmax"}}
UI_PATCH_VERSION = "1.1.0"
UI_PATCH_RELEASE = f"grok-build-ui-v{UI_PATCH_VERSION}"
UI_PATCH_ASSET_BASE = (
    f"https://github.com/braindead-dev/groktimizer/releases/download/{UI_PATCH_RELEASE}"
)
UI_PATCH_ARCHIVE_MEMBERS = (
    "grok",
    "LICENSE",
    "THIRD-PARTY-NOTICES",
    "GROKTIMIZER-NOTICE.txt",
)


class ModelInstallError(RuntimeError):
    """Raised when the custom model cannot be installed safely."""


class BinaryInstallError(RuntimeError):
    """Raised when the branded Grok Build binary cannot be installed safely."""


@dataclass(frozen=True)
class BinaryAsset:
    url: str
    sha256: str


UI_PATCH_ASSETS = {
    ("Darwin", "arm64"): BinaryAsset(
        url=f"{UI_PATCH_ASSET_BASE}/groktimized-grok-build-darwin-arm64.zip",
        sha256="4ecc2e1c2e374b7bcbf1f896cef0e05a3748df4aee4ad7d3e58431868b3f27f9",
    ),
}


@dataclass(frozen=True)
class BinaryInstallResult:
    binary: Path
    manifest: Path
    stock_version: str
    branded_version: str


@dataclass(frozen=True)
class ModelConfig:
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    alias: str = DEFAULT_ALIAS
    name: str = DEFAULT_NAME
    description: str = MANAGED_DESCRIPTION
    context_window: int = 32_768
    max_completion_tokens: int = 8_192
    api_key_env: str | None = None
    make_default: bool = True


def _toml_string(value: str) -> str:
    # JSON strings are valid TOML basic strings and handle quotes/control characters safely.
    return json.dumps(value, ensure_ascii=False)


def normalize_base_url(value: str) -> str:
    base_url = value.strip().rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ModelInstallError("base URL must be an absolute http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ModelInstallError("base URL cannot contain credentials, a query, or a fragment")
    if not parsed.path.endswith("/v1"):
        raise ModelInstallError("base URL must end in /v1")
    return base_url


def validate_auth(config: ModelConfig) -> None:
    parsed = urlparse(config.base_url)
    hostname = parsed.hostname
    if hostname not in LOCAL_HOSTS and parsed.scheme != "https":
        raise ModelInstallError("public endpoints must use HTTPS")
    if (
        hostname not in LOCAL_HOSTS
        and not config.api_key_env
        and config.base_url not in TRUSTED_PUBLIC_ENDPOINTS
    ):
        raise ModelInstallError(
            "public endpoints require --api-key-env; use an SSH tunnel for an authless server"
        )
    if config.api_key_env and not os.environ.get(config.api_key_env):
        raise ModelInstallError(
            f"{config.api_key_env} must be set while probing the authenticated endpoint"
        )


def render_model_table(config: ModelConfig) -> str:
    credential = (
        f"env_key = {_toml_string(config.api_key_env)}"
        if config.api_key_env
        else 'api_key = "not-required"'
    )
    return "\n".join(
        [
            f"[model.{_toml_string(config.alias)}]",
            f"model = {_toml_string(config.model)}",
            f"base_url = {_toml_string(config.base_url)}",
            f"name = {_toml_string(config.name)}",
            f"description = {_toml_string(config.description)}",
            'api_backend = "chat_completions"',
            credential,
            f"context_window = {config.context_window}",
            f"max_completion_tokens = {config.max_completion_tokens}",
            "supports_backend_search = false",
        ]
    )


def render_model_blocks(configs: tuple[ModelConfig, ...]) -> str:
    tables = "\n\n".join(render_model_table(config) for config in configs)
    return f"{BEGIN_MARKER}\n{tables}\n{END_MARKER}"


def render_model_block(config: ModelConfig) -> str:
    return render_model_blocks((config,))


def replace_managed_block(existing: str, block: str) -> str:
    start = existing.find(BEGIN_MARKER)
    end = existing.find(END_MARKER)
    if (start == -1) != (end == -1):
        raise ModelInstallError("existing Groktimizer model block is incomplete")
    if start != -1:
        if end < start:
            raise ModelInstallError("existing Groktimizer model markers are out of order")
        end += len(END_MARKER)
        suffix = existing[end:]
        if suffix.startswith("\n"):
            suffix = suffix[1:]
        updated = f"{existing[:start]}{block}\n{suffix}"
    else:
        separator = "" if not existing else ("\n" if existing.endswith("\n") else "\n\n")
        updated = f"{existing}{separator}{block}\n"
    return updated


def remove_reserialized_managed_model(existing: str, alias: str) -> str:
    """Remove our table after Grok Build has reserialized the config and dropped comments."""
    parsed = tomllib.loads(existing) if existing.strip() else {}
    current = parsed.get("model", {}).get(alias)
    if current is None:
        return existing
    if not isinstance(current, dict) or current.get("description") not in MANAGED_DESCRIPTIONS:
        raise ModelInstallError(f"model alias {alias!r} already exists outside the managed block")

    headers = {f"[model.{_toml_string(alias)}]"}
    if all(character.isalnum() or character in "_-" for character in alias):
        headers.add(f"[model.{alias}]")

    lines = existing.splitlines(keepends=True)
    start = next((index for index, line in enumerate(lines) if line.strip() in headers), None)
    if start is None:
        raise ModelInstallError(f"could not locate managed model table for alias {alias!r}")
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].lstrip().startswith("[")),
        len(lines),
    )
    return "".join(lines[:start] + lines[end:]).rstrip() + "\n"


def set_default_model(existing: str, alias: str) -> str:
    """Set `[models].default` without reserializing or disturbing unrelated settings."""
    value = _toml_string(alias)
    replacement = f"default = {value}\n"
    lines = existing.splitlines(keepends=True)

    dotted_pattern = re.compile(r"^(?P<indent>\s*)models\.default\s*=.*$")
    for index, line in enumerate(lines):
        if line.lstrip().startswith("["):
            break
        match = dotted_pattern.match(line.rstrip("\r\n"))
        if match:
            lines[index] = f"{match.group('indent')}models.default = {value}\n"
            return "".join(lines)

    header = next((index for index, line in enumerate(lines) if line.strip() == "[models]"), None)
    if header is not None:
        end = next(
            (
                index
                for index in range(header + 1, len(lines))
                if lines[index].lstrip().startswith("[")
            ),
            len(lines),
        )
        default_pattern = re.compile(r'^\s*(?:default|"default")\s*=')
        for index in range(header + 1, end):
            if default_pattern.match(lines[index]):
                indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
                lines[index] = f"{indent}{replacement}"
                return "".join(lines)
        lines.insert(header + 1, replacement)
        return "".join(lines)

    parsed = tomllib.loads(existing) if existing.strip() else {}
    if "models" in parsed:
        raise ModelInstallError("cannot safely update an inline [models] table")
    separator = "" if not existing else ("" if existing.endswith("\n\n") else "\n")
    return f"{existing}{separator}[models]\n{replacement}"


def probe_endpoint(config: ModelConfig, timeout: float = 10.0) -> list[str]:
    headers = {"Accept": "application/json"}
    if config.api_key_env:
        headers["Authorization"] = f"Bearer {os.environ[config.api_key_env]}"
    request = urllib.request.Request(  # noqa: S310 - base URL is restricted to HTTP(S)
        f"{config.base_url}/models", headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            payload = json.load(response)
    except (OSError, ValueError, urllib.error.HTTPError) as exc:
        raise ModelInstallError(f"endpoint probe failed: {exc}") from exc
    models = [item.get("id") for item in payload.get("data", []) if isinstance(item, dict)]
    return [model for model in models if isinstance(model, str)]


def model_is_advertised(model: str, available: list[str]) -> bool:
    accepted = {model, *ADVERTISED_MODEL_ALIASES.get(model, set())}
    return bool(accepted.intersection(available))


def default_config_path() -> Path:
    grok_home = Path(os.environ.get("GROK_HOME", Path.home() / ".grok"))
    return grok_home / "config.toml"


def default_grok_home() -> Path:
    return Path(os.environ.get("GROK_HOME", Path.home() / ".grok"))


def current_binary_asset(
    system: str | None = None,
    machine: str | None = None,
) -> BinaryAsset | None:
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    normalized_machine = {
        "aarch64": "arm64",
        "x86_64": "x86_64",
        "amd64": "x86_64",
    }.get(machine, machine)
    return UI_PATCH_ASSETS.get((system, normalized_machine))


def _binary_version(binary: Path) -> str:
    try:
        result = subprocess.run(  # noqa: S603 - path is resolved from our managed install
            [binary, "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BinaryInstallError(f"could not run {binary}: {exc}") from exc
    return (result.stdout or result.stderr).strip()


def _download_binary_archive(asset: BinaryAsset, destination: Path) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", asset.sha256):
        raise BinaryInstallError("branded binary checksum is not configured")
    request = urllib.request.Request(  # noqa: S310 - URL is release-pinned and checksummed
        asset.url,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": f"groktimizer-grok-build-installer/{UI_PATCH_VERSION}",
        },
    )
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
            with destination.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    digest.update(chunk)
                    output.write(chunk)
    except (OSError, urllib.error.HTTPError) as exc:
        raise BinaryInstallError(f"branded binary download failed: {exc}") from exc
    actual = digest.hexdigest()
    if actual != asset.sha256:
        destination.unlink(missing_ok=True)
        raise BinaryInstallError(
            f"branded binary checksum mismatch (expected {asset.sha256}, got {actual})"
        )


def _extract_binary_archive(archive: Path, staging: Path) -> Path:
    try:
        with zipfile.ZipFile(archive) as bundle:
            names = tuple(bundle.namelist())
            if set(names) != set(UI_PATCH_ARCHIVE_MEMBERS) or len(names) != len(
                UI_PATCH_ARCHIVE_MEMBERS
            ):
                raise BinaryInstallError(f"unexpected files in branded binary archive: {names}")
            for name in UI_PATCH_ARCHIVE_MEMBERS:
                destination = staging / name
                with bundle.open(name) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)
    except (OSError, zipfile.BadZipFile) as exc:
        raise BinaryInstallError(f"invalid branded binary archive: {exc}") from exc
    binary = staging / "grok"
    binary.chmod(0o755)
    return binary


def _atomic_symlink(target: str, link: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    temporary = link.with_name(f".{link.name}.groktimized.{os.getpid()}")
    temporary.unlink(missing_ok=True)
    try:
        temporary.symlink_to(target)
        os.replace(temporary, link)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w") as output:
            json.dump(payload, output, indent=2, sort_keys=True)
            output.write("\n")
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _is_branded_target(link: Path, branded_root: Path) -> bool:
    if not (link.exists() or link.is_symlink()):
        return False
    try:
        link.resolve(strict=False).relative_to(branded_root.resolve())
    except ValueError:
        return False
    return True


def _capture_link_state(link: Path, backup_root: Path) -> dict[str, object]:
    if link.is_symlink():
        return {"kind": "symlink", "target": os.readlink(link)}
    if link.exists() and link.is_file():
        backup_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup = backup_root / f"{link.name}.{timestamp}"
        shutil.copy2(link, backup)
        return {
            "kind": "file",
            "backup": str(backup),
            "mode": link.stat().st_mode & 0o777,
        }
    return {"kind": "absent"}


def _restore_link_state(link: Path, state: dict[str, object]) -> None:
    kind = state.get("kind")
    if kind == "symlink":
        target = state.get("target")
        if not isinstance(target, str):
            raise BinaryInstallError(f"invalid saved symlink state for {link}")
        _atomic_symlink(target, link)
        return
    if kind == "file":
        backup_value = state.get("backup")
        if not isinstance(backup_value, str):
            raise BinaryInstallError(f"invalid saved file state for {link}")
        backup = Path(backup_value)
        if not backup.is_file():
            raise BinaryInstallError(f"stock binary backup is missing: {backup}")
        handle, temporary_name = tempfile.mkstemp(prefix=f".{link.name}.", dir=link.parent)
        os.close(handle)
        temporary = Path(temporary_name)
        try:
            shutil.copy2(backup, temporary)
            mode = state.get("mode")
            temporary.chmod(mode if isinstance(mode, int) else 0o755)
            os.replace(temporary, link)
        finally:
            temporary.unlink(missing_ok=True)
        return
    if kind == "absent":
        link.unlink(missing_ok=True)
        return
    raise BinaryInstallError(f"invalid saved link kind for {link}: {kind!r}")


def install_branded_binary(
    grok_home: Path,
    grok_binary: Path,
    asset: BinaryAsset,
) -> BinaryInstallResult:
    """Install the checksummed UI-patched binary and atomically route stock links to it."""
    managed_bin = grok_home / "bin"
    grok_link = managed_bin / "grok"
    branded_root = grok_home / "groktimized"
    manifest_path = branded_root / "install.json"
    version_root = branded_root / UI_PATCH_VERSION
    if not (grok_link.exists() or grok_link.is_symlink()):
        raise BinaryInstallError(f"stock Grok Build link is missing: {grok_link}")
    if grok_binary.resolve() != grok_link.resolve():
        raise BinaryInstallError(
            f"grok resolves outside the stock managed install ({grok_binary} != {grok_link})"
        )

    manifest: dict[str, object] | None = None
    if manifest_path.is_file() and _is_branded_target(grok_link, branded_root):
        try:
            loaded = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise BinaryInstallError(f"could not read prior install manifest: {exc}") from exc
        if isinstance(loaded, dict) and isinstance(loaded.get("links"), dict):
            manifest = loaded
        else:
            raise BinaryInstallError("prior install manifest is invalid")

    if manifest is None:
        stock_version = _binary_version(grok_binary.resolve())
        links = {
            name: _capture_link_state(managed_bin / name, branded_root / "backups")
            for name in ("grok", "agent")
            if (managed_bin / name).exists() or (managed_bin / name).is_symlink()
        }
        manifest = {
            "schema": 1,
            "active": False,
            "stock_version": stock_version,
            "links": links,
        }
    else:
        stock_version_value = manifest.get("stock_version")
        stock_version = stock_version_value if isinstance(stock_version_value, str) else "unknown"
        links_value = manifest["links"]
        links = links_value if isinstance(links_value, dict) else {}

    branded_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".install.", dir=branded_root) as temporary_name:
        staging = Path(temporary_name)
        archive = staging / "bundle.zip"
        _download_binary_archive(asset, archive)
        staged_binary = _extract_binary_archive(archive, staging)
        branded_version = _binary_version(staged_binary)
        version_root.mkdir(parents=True, exist_ok=True)
        for name in UI_PATCH_ARCHIVE_MEMBERS:
            source = staging / name
            destination = version_root / name
            os.replace(source, destination)
        installed_binary = version_root / "grok"
        installed_binary.chmod(0o755)

    swapped: list[str] = []
    try:
        for name in links:
            link = managed_bin / name
            relative_target = os.path.relpath(installed_binary, start=link.parent)
            _atomic_symlink(relative_target, link)
            swapped.append(name)
    except OSError as exc:
        for name in reversed(swapped):
            state = links.get(name)
            if isinstance(state, dict):
                _restore_link_state(managed_bin / name, state)
        raise BinaryInstallError(f"could not activate branded Grok Build: {exc}") from exc

    manifest.update(
        {
            "active": True,
            "ui_patch_version": UI_PATCH_VERSION,
            "branded_binary": str(installed_binary),
            "branded_version": branded_version,
            "installed_at": datetime.now(UTC).isoformat(),
        }
    )
    try:
        _atomic_json(manifest_path, manifest)
    except OSError as exc:
        for name, state in links.items():
            if isinstance(state, dict):
                _restore_link_state(managed_bin / name, state)
        raise BinaryInstallError(f"could not save branded install state: {exc}") from exc
    return BinaryInstallResult(
        binary=installed_binary,
        manifest=manifest_path,
        stock_version=stock_version,
        branded_version=branded_version,
    )


def restore_stock_binary(grok_home: Path) -> Path:
    """Restore every Grok Build entrypoint captured before the branded swap."""
    branded_root = grok_home / "groktimized"
    manifest_path = branded_root / "install.json"
    if not manifest_path.is_file():
        raise BinaryInstallError("no Groktimized Grok Build installation was found")
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise BinaryInstallError(f"could not read install manifest: {exc}") from exc
    links = manifest.get("links") if isinstance(manifest, dict) else None
    if not isinstance(links, dict):
        raise BinaryInstallError("install manifest has no restorable link state")
    for name, state in links.items():
        if not isinstance(name, str) or not isinstance(state, dict):
            raise BinaryInstallError("install manifest contains invalid link state")
        _restore_link_state(grok_home / "bin" / name, state)
    manifest["active"] = False
    manifest["restored_at"] = datetime.now(UTC).isoformat()
    _atomic_json(manifest_path, manifest)
    return manifest_path


def install_model_configs(
    path: Path,
    configs: tuple[ModelConfig, ...],
    *,
    default_alias: str | None,
) -> Path | None:
    if not configs:
        raise ModelInstallError("at least one model configuration is required")
    aliases = [config.alias for config in configs]
    if len(set(aliases)) != len(aliases):
        raise ModelInstallError("model aliases must be unique")

    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text() if path.exists() else ""
    if BEGIN_MARKER not in existing:
        for alias in (*aliases, *LEGACY_ALIASES):
            existing = remove_reserialized_managed_model(existing, alias)

    updated = replace_managed_block(existing, render_model_blocks(configs))
    if default_alias is not None:
        if default_alias not in aliases:
            raise ModelInstallError("default model alias must be managed by this install")
        updated = set_default_model(updated, default_alias)
    try:
        tomllib.loads(updated)
    except tomllib.TOMLDecodeError as exc:
        raise ModelInstallError(f"updated Grok config would be invalid TOML: {exc}") from exc

    backup = None
    if path.exists():
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup = path.with_name(f"{path.name}.bak.{timestamp}")
        shutil.copy2(path, backup)

    handle, temporary_name = tempfile.mkstemp(prefix="config.toml.", dir=path.parent, text=True)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(handle, "w") as temporary:
            temporary.write(updated)
        temporary_path.chmod(0o600)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return backup


def install_model_config(path: Path, config: ModelConfig) -> Path | None:
    return install_model_configs(
        path,
        (config,),
        default_alias=config.alias if config.make_default else None,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Add the optimized Groktimizer endpoint to Grok Build."
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("GROKTIMIZER_MODEL_BASE_URL", DEFAULT_BASE_URL),
        help="OpenAI-compatible base URL ending in /v1 (or GROKTIMIZER_MODEL_BASE_URL)",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="model ID sent to the endpoint")
    parser.add_argument("--alias", default=DEFAULT_ALIAS, help="Grok Build model alias")
    parser.add_argument("--name", default=DEFAULT_NAME, help="model-picker display name")
    parser.add_argument("--context-window", type=int, default=32_768)
    parser.add_argument("--max-completion-tokens", type=int, default=8_192)
    parser.add_argument(
        "--api-key-env",
        help="environment variable containing a dedicated key for a public endpoint",
    )
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument(
        "--skip-probe",
        action="store_true",
        help="write the model entry without checking /v1/models",
    )
    parser.add_argument(
        "--no-default",
        action="store_true",
        help="add the model without selecting it as the default for new sessions",
    )
    parser.add_argument(
        "--config-only",
        action="store_true",
        help="register the model without installing the purple Grok Build UI patch",
    )
    parser.add_argument(
        "--restore-stock",
        action="store_true",
        help="restore the stock Grok Build binary links and exit",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    grok_binary_value = shutil.which("grok")
    if grok_binary_value is None:
        parser.error("Grok Build is not installed; run https://x.ai/cli/install.sh first")
    grok_binary = Path(grok_binary_value)
    grok_home = default_grok_home()

    if args.restore_stock:
        try:
            manifest = restore_stock_binary(grok_home)
        except BinaryInstallError as exc:
            parser.error(str(exc))
        print(f"Restored stock Grok Build using {manifest}")
        return

    asset = None if args.config_only else current_binary_asset()
    if asset is None and not args.config_only:
        parser.error(
            "the purple UI patch currently supports macOS on Apple Silicon; "
            "pass --config-only to register the model without the UI patch"
        )

    try:
        primary_config = ModelConfig(
            base_url=normalize_base_url(args.base_url),
            model=args.model,
            alias=args.alias,
            name=args.name,
            context_window=args.context_window,
            max_completion_tokens=args.max_completion_tokens,
            api_key_env=args.api_key_env,
            make_default=not args.no_default,
        )
        standard_config = ModelConfig(
            base_url=STANDARD_BASE_URL,
            model=STANDARD_MODEL,
            alias=STANDARD_ALIAS,
            name=STANDARD_NAME,
            description=STANDARD_MANAGED_DESCRIPTION,
            make_default=False,
        )
        configs = (primary_config, standard_config)
        for config in configs:
            validate_auth(config)
            if not args.skip_probe:
                available = probe_endpoint(config)
                if available and not model_is_advertised(config.model, available):
                    raise ModelInstallError(
                        f"model {config.model!r} is not advertised by the endpoint: {available}"
                    )
        backup = install_model_configs(
            args.config,
            configs,
            default_alias=primary_config.alias if primary_config.make_default else None,
        )
        binary_result = (
            install_branded_binary(grok_home, grok_binary, asset) if asset is not None else None
        )
    except (BinaryInstallError, ModelInstallError) as exc:
        parser.error(str(exc))

    for config in configs:
        print(f"Added {config.name} as {config.alias!r} in {args.config}")
    if backup:
        print(f"Backup: {backup}")
    if primary_config.make_default:
        print("Set as the default for new Grok Build sessions.")
    if binary_result:
        print(f"Installed the purple Grok Build UI patch: {binary_result.binary}")
        print(f"Stock binary state is preserved in: {binary_result.manifest}")
        print(
            "Restore anytime: curl -fsSL https://groktimizer.com/install.sh "
            "| sh -s -- --restore-stock"
        )
    print("Open Grok Build normally: grok")
    print(f"Switch anytime: /model {primary_config.alias} or /model {standard_config.alias}")


def launch_fast_model() -> None:
    """Open stock Grok Build with the Groktimized model selected."""
    grok_binary = shutil.which("grok")
    if grok_binary is None:
        raise SystemExit("Grok Build is not installed; run https://x.ai/cli/install.sh first")

    alias = os.environ.get("GROKTIMIZER_GROK_ALIAS", DEFAULT_ALIAS)
    os.execv(grok_binary, [grok_binary, "-m", alias, *sys.argv[1:]])  # noqa: S606


if __name__ == "__main__":
    main()
