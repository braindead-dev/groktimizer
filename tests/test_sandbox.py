# tests/test_sandbox.py
from groktimizer.core.sandbox import agent_labels, sandbox_name

def test_sandbox_name():
    assert sandbox_name("demo", "hq", "main") == "gtz-demo-hq-main"

def test_agent_labels():
    labels = agent_labels("demo", "attn", "impl-1", "implementer")
    assert labels == {
        "gtz-project": "demo", "gtz-team": "attn",
        "gtz-agent": "impl-1", "gtz-role": "implementer",
    }


def test_validate_name():
    import pytest
    from groktimizer.core.sandbox import InvalidNameError, validate_name
    validate_name("team", "attn2")
    for bad in ("attn-opt", "Attn", "", "a" * 25, "a b", "a/b"):
        with pytest.raises(InvalidNameError):
            validate_name("team", bad)
