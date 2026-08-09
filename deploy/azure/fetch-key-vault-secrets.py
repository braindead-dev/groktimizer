#!/usr/bin/env python3
"""Materialize the API service environment from Key Vault using the VM identity."""

from __future__ import annotations

import json
import os
import pwd
import shlex
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

IMDS_TOKEN_URL = "http://169.254.169.254/metadata/identity/oauth2/token"  # noqa: S105
OUTPUT_PATH = Path("/run/groktimizer/secrets.env")
REQUIRED_SECRETS = {
    "bl-api-key": "BL_API_KEY",
    "bl-workspace": "BL_WORKSPACE",
    "runpod-api-key": "RUNPOD_API_KEY",
    "xai-api-key": "XAI_API_KEY",
    "github-token": "GITHUB_TOKEN",
    "gtz-api-token": "GTZ_API_TOKEN",
    "gtz-stream-signing-key": "GTZ_STREAM_SIGNING_KEY",
}
OPTIONAL_SECRETS = {
    "xai-api-key-2": "XAI_API_KEY_2",
    "groktimizer-model-api-key": "GROKTIMIZER_MODEL_API_KEY",
}


def read_json(url: str, headers: dict[str, str]) -> dict:
    request = urllib.request.Request(url, headers=headers)  # noqa: S310
    with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
        value = json.loads(response.read())
    if not isinstance(value, dict):
        raise RuntimeError(f"unexpected JSON response from {urllib.parse.urlparse(url).hostname}")
    return value


def identity_token() -> str:
    query = urllib.parse.urlencode(
        {
            "api-version": "2018-02-01",
            "resource": "https://vault.azure.net",
        }
    )
    value = read_json(f"{IMDS_TOKEN_URL}?{query}", {"Metadata": "true"})
    token = value.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("managed identity did not return a Key Vault token")
    return token


def secret(vault: str, name: str, token: str, *, required: bool) -> str | None:
    url = f"https://{vault}.vault.azure.net/secrets/{name}?api-version=7.4"
    try:
        value = read_json(url, {"Authorization": f"Bearer {token}"}).get("value")
    except urllib.error.HTTPError as error:
        if error.code == 404 and not required:
            return None
        raise
    if not isinstance(value, str) or (required and not value):
        raise RuntimeError(f"Key Vault secret {name} is empty")
    return value


def main() -> None:
    vault = os.environ.get("GTZ_KEY_VAULT", "")
    if not vault:
        raise RuntimeError("GTZ_KEY_VAULT is required")
    token = identity_token()
    values: dict[str, str] = {}
    for name, environment_name in REQUIRED_SECRETS.items():
        values[environment_name] = secret(vault, name, token, required=True) or ""
    for name, environment_name in OPTIONAL_SECRETS.items():
        value = secret(vault, name, token, required=False)
        if value:
            values[environment_name] = value

    OUTPUT_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=OUTPUT_PATH.parent, text=True)
    try:
        with os.fdopen(descriptor, "w") as output:
            for key, value in sorted(values.items()):
                output.write(f"{key}={shlex.quote(value)}\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary_name, 0o600)
        account = pwd.getpwnam("groktimizer")
        os.chown(temporary_name, account.pw_uid, account.pw_gid)
        os.replace(temporary_name, OUTPUT_PATH)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


if __name__ == "__main__":
    main()
