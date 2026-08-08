from groktimizer.cli.main import format_tree
from groktimizer.core.registry import AgentInfo


def test_format_tree():
    agents = [
        AgentInfo("demo", "hq", "main", "main", "gtz-demo-hq-main"),
        AgentInfo("demo", "attn", "lead", "team", "gtz-demo-attn-lead"),
        AgentInfo("demo", "attn", "impl-1", "implementer", "gtz-demo-attn-impl-1"),
    ]
    out = format_tree(agents)
    assert out.index("main") < out.index("attn") < out.index("impl-1")
