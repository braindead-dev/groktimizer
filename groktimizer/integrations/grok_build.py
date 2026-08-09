"""Safely register the fastest Groktimizer endpoint as a Grok Build model."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

BEGIN_MARKER = "# >>> groktimizer fast model >>>"
END_MARKER = "# <<< groktimizer fast model <<<"
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
DEFAULT_BASE_URL = "https://z08tqd2khleyx4-8000.proxy.runpod.net/v1"
DEFAULT_MODEL = "grok-2"
DEFAULT_ALIAS = "groktimized-2"
DEFAULT_NAME = "🟣 Groktimized 2"
LEGACY_ALIASES = ("groktimizer-fast",)
MANAGED_DESCRIPTION = "Optimized Grok 2 deployment by Groktimizer"
MANAGED_DESCRIPTIONS = {
    MANAGED_DESCRIPTION,
    "Optimized Grok deployment managed by Groktimizer",
}
TRUSTED_PUBLIC_ENDPOINTS = {DEFAULT_BASE_URL}


class ModelInstallError(RuntimeError):
    """Raised when the custom model cannot be installed safely."""


@dataclass(frozen=True)
class ModelConfig:
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    alias: str = DEFAULT_ALIAS
    name: str = DEFAULT_NAME
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


def render_model_block(config: ModelConfig) -> str:
    credential = (
        f"env_key = {_toml_string(config.api_key_env)}"
        if config.api_key_env
        else 'api_key = "not-required"'
    )
    return "\n".join(
        [
            BEGIN_MARKER,
            f"[model.{_toml_string(config.alias)}]",
            f"model = {_toml_string(config.model)}",
            f"base_url = {_toml_string(config.base_url)}",
            f"name = {_toml_string(config.name)}",
            f"description = {_toml_string(MANAGED_DESCRIPTION)}",
            'api_backend = "chat_completions"',
            credential,
            f"context_window = {config.context_window}",
            f"max_completion_tokens = {config.max_completion_tokens}",
            "supports_backend_search = false",
            END_MARKER,
        ]
    )


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


def default_config_path() -> Path:
    grok_home = Path(os.environ.get("GROK_HOME", Path.home() / ".grok"))
    return grok_home / "config.toml"


def install_model_config(path: Path, config: ModelConfig) -> Path | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text() if path.exists() else ""
    if BEGIN_MARKER not in existing:
        for alias in (config.alias, *LEGACY_ALIASES):
            existing = remove_reserialized_managed_model(existing, alias)

    updated = replace_managed_block(existing, render_model_block(config))
    if config.make_default:
        updated = set_default_model(updated, config.alias)
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
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if shutil.which("grok") is None:
        parser.error("Grok Build is not installed; run https://x.ai/cli/install.sh first")

    try:
        config = ModelConfig(
            base_url=normalize_base_url(args.base_url),
            model=args.model,
            alias=args.alias,
            name=args.name,
            context_window=args.context_window,
            max_completion_tokens=args.max_completion_tokens,
            api_key_env=args.api_key_env,
            make_default=not args.no_default,
        )
        validate_auth(config)
        if not args.skip_probe:
            available = probe_endpoint(config)
            if available and config.model not in available:
                raise ModelInstallError(
                    f"model {config.model!r} is not advertised by the endpoint: {available}"
                )
        backup = install_model_config(args.config, config)
    except ModelInstallError as exc:
        parser.error(str(exc))

    print(f"Added {config.name} as {config.alias!r} in {args.config}")
    if backup:
        print(f"Backup: {backup}")
    if config.make_default:
        print("Set as the default for new Grok Build sessions.")
    print("Open Grok Build normally: grok")
    print(f"Switch anytime: /model {config.alias}")


def launch_fast_model() -> None:
    """Open stock Grok Build with the Groktimized model selected."""
    grok_binary = shutil.which("grok")
    if grok_binary is None:
        raise SystemExit("Grok Build is not installed; run https://x.ai/cli/install.sh first")

    alias = os.environ.get("GROKTIMIZER_GROK_ALIAS", DEFAULT_ALIAS)
    os.execv(grok_binary, [grok_binary, "-m", alias, *sys.argv[1:]])  # noqa: S606


if __name__ == "__main__":
    main()
