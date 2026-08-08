import pytest
from groktimizer.mcp.server import PermissionError_, check_manage, check_spawn


def test_main_spawns_anywhere():
    check_spawn(actor_role="main", actor_team="hq", target_role="team", target_team="newteam")
    check_spawn(actor_role="main", actor_team="hq", target_role="implementer", target_team="attn")


def test_team_orch_spawns_only_own_implementers():
    check_spawn(actor_role="team", actor_team="attn",
                target_role="implementer", target_team="attn")
    with pytest.raises(PermissionError_):
        check_spawn(actor_role="team", actor_team="attn",
                    target_role="implementer", target_team="gemm")
    with pytest.raises(PermissionError_):
        check_spawn(actor_role="team", actor_team="attn",
                    target_role="team", target_team="new")


def test_implementer_spawns_nothing():
    with pytest.raises(PermissionError_):
        check_spawn(actor_role="implementer", actor_team="attn",
                    target_role="implementer", target_team="attn")


def test_manage_scope():
    check_manage(actor_role="main", actor_team="hq", target_team="attn")
    check_manage(actor_role="team", actor_team="attn", target_team="attn")
    with pytest.raises(PermissionError_):
        check_manage(actor_role="team", actor_team="attn", target_team="gemm")
    with pytest.raises(PermissionError_):
        check_manage(actor_role="implementer", actor_team="attn", target_team="attn")


def test_reconciler_gating():
    check_spawn(actor_role="main", actor_team="hq", target_role="reconciler", target_team="hq")
    with pytest.raises(PermissionError_):
        check_spawn(actor_role="team", actor_team="attn",
                    target_role="reconciler", target_team="hq")
    with pytest.raises(PermissionError_):
        check_spawn(actor_role="reconciler", actor_team="hq",
                    target_role="implementer", target_team="attn")


def test_unknown_role_rejected():
    with pytest.raises(PermissionError_, match="unknown role"):
        check_spawn(actor_role="main", actor_team="hq",
                    target_role="supervisor", target_team="x")
