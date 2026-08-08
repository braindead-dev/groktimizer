from groktimizer.config import Config
from groktimizer.prompts import render_brief

CFG = Config(project="demo", shared_repo="git@x:y.git", tooling_repo="https://g/o/r.git")


def test_render_each_role():
    for role in ("main", "team", "implementer", "reconciler"):
        text = render_brief(role, CFG, team="attn", agent="a1", brief="Optimize softmax")
        assert "Optimize softmax" in text
        assert "demo" in text
        assert "{" not in text  # no unfilled placeholders


def test_braces_in_brief_are_safe():
    brief = 'Try config {"batch_size": 64} and shapes {M}x{N}'
    text = render_brief("implementer", CFG, team="attn", agent="a1", brief=brief)
    assert '{"batch_size": 64}' in text
    assert "{M}x{N}" in text


def test_thresholds_rendered():
    text = render_brief("team", CFG, team="attn", agent="lead", brief="b")
    assert "5%" in text
    assert CFG.research.benchmark_cmd in text
    assert CFG.research.accuracy_cmd in text
