import hashlib
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

from groktimizer.integrations.grok_build import (
    BEGIN_MARKER,
    DEFAULT_BASE_URL,
    BinaryAsset,
    ModelConfig,
    ModelInstallError,
    current_binary_asset,
    install_branded_binary,
    install_model_config,
    launch_fast_model,
    normalize_base_url,
    render_model_block,
    restore_stock_binary,
    validate_auth,
)


def test_local_model_uses_dummy_key_to_avoid_xai_credential_fallback():
    block = render_model_block(ModelConfig(base_url="http://127.0.0.1:8000/v1"))
    assert 'api_key = "not-required"' in block
    assert "env_key" not in block
    assert 'api_backend = "chat_completions"' in block


def test_install_preserves_config_and_is_idempotent(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[cli]\ninstaller = "internal"\n')
    first = ModelConfig(base_url="http://localhost:8000/v1")
    install_model_config(path, first)
    second = ModelConfig(base_url="http://localhost:9000/v1", name="Faster Grok")
    backup = install_model_config(path, second)

    text = path.read_text()
    parsed = tomllib.loads(text)
    assert text.count(BEGIN_MARKER) == 1
    assert parsed["cli"]["installer"] == "internal"
    assert parsed["models"]["default"] == "groktimized-2"
    assert parsed["model"]["groktimized-2"]["name"] == "Faster Grok"
    assert parsed["model"]["groktimized-2"]["base_url"] == "http://localhost:9000/v1"
    assert backup is not None and backup.exists()
    assert path.stat().st_mode & 0o777 == 0o600


def test_install_recovers_after_grok_reserializes_managed_table(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        'disabled_mcp_servers = ["PostHog"]\n\n'
        "[model.groktimizer-fast]\n"
        'model = "old-model"\n'
        'base_url = "http://localhost:8000/v1"\n'
        'description = "Optimized Grok deployment managed by Groktimizer"\n'
    )

    install_model_config(path, ModelConfig(base_url="http://localhost:9000/v1"))

    text = path.read_text()
    parsed = tomllib.loads(text)
    assert text.count(BEGIN_MARKER) == 1
    assert parsed["disabled_mcp_servers"] == ["PostHog"]
    assert "groktimizer-fast" not in parsed["model"]
    assert parsed["model"]["groktimized-2"]["base_url"] == "http://localhost:9000/v1"


def test_install_does_not_overwrite_foreign_alias(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[model.groktimized-2]\nmodel = "someone-elses-model"\ndescription = "Unrelated model"\n'
    )

    with pytest.raises(ModelInstallError, match="already exists outside"):
        install_model_config(path, ModelConfig(base_url="http://localhost:9000/v1"))


def test_public_endpoint_requires_dedicated_key(monkeypatch):
    config = ModelConfig(base_url="https://example.com/v1")
    with pytest.raises(ModelInstallError, match="public endpoints require"):
        validate_auth(config)

    keyed = ModelConfig(base_url="https://example.com/v1", api_key_env="FAST_GROK_KEY")
    with pytest.raises(ModelInstallError, match="FAST_GROK_KEY must be set"):
        validate_auth(keyed)
    monkeypatch.setenv("FAST_GROK_KEY", "secret")
    validate_auth(keyed)

    insecure = ModelConfig(base_url="http://example.com/v1", api_key_env="FAST_GROK_KEY")
    with pytest.raises(ModelInstallError, match="must use HTTPS"):
        validate_auth(insecure)

    validate_auth(ModelConfig())
    assert ModelConfig().base_url == DEFAULT_BASE_URL
    assert ModelConfig().base_url == "https://xwdq0i6koerlhu-8000.proxy.runpod.net/v1"
    assert ModelConfig().model == "grok-2-fast"
    assert ModelConfig().name == "Groktimized 2"


def test_binary_asset_normalizes_apple_silicon_architecture():
    assert current_binary_asset("Darwin", "arm64") is not None
    assert current_binary_asset("Darwin", "aarch64") is not None
    assert current_binary_asset("Linux", "arm64") is None


def test_branded_binary_install_is_atomic_and_restorable(tmp_path):
    grok_home = tmp_path / ".grok"
    downloads = grok_home / "downloads"
    managed_bin = grok_home / "bin"
    downloads.mkdir(parents=True)
    managed_bin.mkdir()
    stock = downloads / "grok-macos-aarch64"
    stock.write_text("#!/bin/sh\nprintf 'grok 1.0.0 stock\\n'\n")
    stock.chmod(0o755)
    for name in ("grok", "agent"):
        (managed_bin / name).symlink_to("../downloads/grok-macos-aarch64")

    archive = tmp_path / "branded.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("grok", "#!/bin/sh\nprintf 'grok 1.0.0 branded\\n'\n")
        bundle.writestr("LICENSE", "Apache-2.0")
        bundle.writestr("THIRD-PARTY-NOTICES", "notices")
        bundle.writestr("GROKTIMIZER-NOTICE.txt", "modified build")
    asset = BinaryAsset(
        url=archive.as_uri(),
        sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
    )

    result = install_branded_binary(grok_home, managed_bin / "grok", asset)

    assert result.stock_version == "grok 1.0.0 stock"
    assert result.branded_version == "grok 1.0.0 branded"
    assert (managed_bin / "grok").resolve() == result.binary
    assert (managed_bin / "agent").resolve() == result.binary
    assert result.binary.stat().st_mode & 0o111
    assert stock.exists()
    assert result.manifest.stat().st_mode & 0o777 == 0o600

    repeated = install_branded_binary(grok_home, managed_bin / "grok", asset)
    assert repeated.stock_version == "grok 1.0.0 stock"
    assert (managed_bin / "grok").resolve() == repeated.binary

    restore_stock_binary(grok_home)

    assert (managed_bin / "grok").readlink() == Path("../downloads/grok-macos-aarch64")
    assert (managed_bin / "agent").readlink() == Path("../downloads/grok-macos-aarch64")
    assert (managed_bin / "grok").resolve() == stock


def test_install_can_preserve_existing_default(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[models]\ndefault = "grok-4.5"\n')

    install_model_config(
        path,
        ModelConfig(base_url="http://localhost:8000/v1", make_default=False),
    )

    assert tomllib.loads(path.read_text())["models"]["default"] == "grok-4.5"


def test_install_replaces_existing_default_without_touching_other_model_settings(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[models]\ndefault = "grok-4.5"\nweb_search = "grok-4.5"\n\n[ui]\nsimple_mode = true\n'
    )

    install_model_config(path, ModelConfig(base_url="http://localhost:8000/v1"))

    parsed = tomllib.loads(path.read_text())
    assert parsed["models"] == {
        "default": "groktimized-2",
        "web_search": "grok-4.5",
    }
    assert parsed["ui"]["simple_mode"] is True


@pytest.mark.parametrize(
    "value",
    [
        "example.com/v1",
        "ftp://example.com/v1",
        "https://x.test",
        "https://user:secret@x.test/v1",
        "https://x.test/v1?token=secret",
    ],
)
def test_base_url_must_be_http_and_end_in_v1(value):
    with pytest.raises(ModelInstallError):
        normalize_base_url(value)


def test_fast_model_launcher_loads_repo_env_and_execs_grok(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("GROKTIMIZER_MODEL_API_KEY=test-key\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GROKTIMIZER_MODEL_API_KEY", raising=False)
    monkeypatch.setattr("groktimizer.integrations.grok_build.shutil.which", lambda _: "/bin/grok")
    monkeypatch.setattr(sys, "argv", ["gtz-grok", "-p", "hello"])
    invocation = {}

    def fake_execv(binary, args):
        invocation.update(binary=binary, args=args)

    monkeypatch.setattr("groktimizer.integrations.grok_build.os.execv", fake_execv)

    launch_fast_model()

    assert invocation == {
        "binary": "/bin/grok",
        "args": ["/bin/grok", "-m", "groktimized-2", "-p", "hello"],
    }


def test_website_installer_matches_repository_installer():
    root = Path(__file__).resolve().parents[1]
    assert (root / "frontend/public/install.sh").read_bytes() == (root / "install.sh").read_bytes()
