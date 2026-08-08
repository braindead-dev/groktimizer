import tomllib

import pytest

from groktimizer.integrations.grok_build import (
    BEGIN_MARKER,
    ModelConfig,
    ModelInstallError,
    install_model_config,
    normalize_base_url,
    render_model_block,
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
    assert parsed["model"]["groktimizer-fast"]["base_url"] == "http://localhost:9000/v1"
    assert backup is not None and backup.exists()
    assert path.stat().st_mode & 0o777 == 0o600


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
