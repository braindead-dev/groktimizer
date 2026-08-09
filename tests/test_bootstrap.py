import json

# tests/test_bootstrap.py
from groktimizer.config import Budget, Caps, Config
from groktimizer.core.bootstrap import prepare_agent_secrets, spawn_agent
from tests.fakes import FakeSandboxClient

CFG = Config(
    project="demo",
    shared_repo="git@x:y.git",
    tooling_repo="https://github.com/o/groktimizer.git",
    caps=Caps(),
    budget=Budget(),
)


async def test_spawn_creates_configured_sandbox():
    client = FakeSandboxClient()
    name = await spawn_agent(
        CFG,
        client,
        team="attn",
        agent="impl1",
        role="implementer",
        brief="Optimize softmax",
        extra_envs={"RUNPOD_API_KEY": "k"},
    )
    assert name == "gtz-demo-attn-impl1"
    meta = client.sandboxes[name]
    assert meta.labels["gtz-role"] == "implementer"
    # brief and setup script written into the sandbox
    assert "Optimize softmax" in client.files[(name, "/opt/gtz/brief.md")]
    setup = client.files[(name, "/opt/gtz/setup.sh")]
    assert "x.ai/cli/install.sh" in setup
    assert "tmux new-session" in setup
    assert "grok mcp remove groktimizer" in setup
    assert 'git checkout -B "$GTZ_BRANCH"' in setup
    assert 'git push -u origin "$GTZ_BRANCH"' in setup
    # setup executed
    assert any("setup.sh" in cmd for _, cmd in client.execs)


async def test_hyphenated_names_rejected():
    import pytest

    from groktimizer.core.sandbox import InvalidNameError

    client = FakeSandboxClient()
    with pytest.raises(InvalidNameError):
        await spawn_agent(CFG, client, team="attn-opt", agent="a1", role="implementer", brief="x")


async def test_reconciler_gets_model_override():
    from groktimizer.config import Research

    cfg = CFG.model_copy(update={"research": Research(reconciler_model="grok-4-max")})
    client = FakeSandboxClient()
    captured = {}
    orig = client.create

    async def create(name, image, region, labels, envs):
        captured.update(envs)
        await orig(name, image, region, labels, envs)

    client.create = create
    await spawn_agent(
        cfg,
        client,
        team="hq",
        agent="reconciler",
        role="reconciler",
        brief="merge it all",
    )
    assert captured["GTZ_GROK_MODEL"] == "grok-4-max"
    assert captured["GTZ_REASONING_EFFORT"] == "high"


async def test_agent_roles_get_pinned_models():
    client = FakeSandboxClient()
    captured = {}
    orig = client.create

    async def create(name, image, region, labels, envs):
        captured.update(envs)
        await orig(name, image, region, labels, envs)

    client.create = create
    await spawn_agent(
        CFG, client, team="attn", agent="impl3", role="implementer", brief="measure it"
    )
    assert captured["GTZ_GROK_MODEL"] == "grok-4.5"
    assert captured["GTZ_REASONING_EFFORT"] == "high"
    assert captured["GTZ_BRANCH"] == "agent/attn/impl3"
    setup = client.files[("gtz-demo-attn-impl3", "/opt/gtz/setup.sh")]
    runner = client.files[("gtz-demo-attn-impl3", "/opt/gtz/agent_runner.py")]
    assert "agent_runner.py daemon" in setup
    assert "GTZ_REASONING_EFFORT" in runner
    assert "GTZ_SESSION_ID" in captured


async def test_secrets_go_to_env_file_not_create_envs():
    client = FakeSandboxClient()
    captured = {}
    orig = client.create

    async def create(name, image, region, labels, envs):
        captured.update(envs)
        await orig(name, image, region, labels, envs)

    client.create = create
    name = await spawn_agent(
        CFG,
        client,
        team="attn",
        agent="impl2",
        role="implementer",
        brief="x",
        extra_envs={
            "RUNPOD_API_KEY": "sekret",
            "XAI_API_KEY": "x'y",
            "GITHUB_TOKEN": "github-secret",
        },
    )
    assert "RUNPOD_API_KEY" not in captured  # not in control-plane envs
    assert "XAI_API_KEY" not in captured
    assert "GITHUB_TOKEN" not in captured
    env_file = client.files[(name, "/opt/gtz/.env")]
    assert "export RUNPOD_API_KEY=sekret" in env_file
    assert "export GITHUB_TOKEN=github-secret" in env_file
    assert "x'\"'\"'y" in env_file  # shell-quoted
    assert any("chmod 600 /opt/gtz/.env" in cmd for _, cmd in client.execs)
    # setup script sources it with xtrace disabled and the tmux line sources it too
    setup = client.files[(name, "/opt/gtz/setup.sh")]
    assert setup.count("/opt/gtz/.env") >= 2
    assert "GIT_ASKPASS=/opt/gtz/git-askpass.sh" in setup
    assert 'git config --global user.name "Groktimizer"' in setup


def test_xai_key_pool_is_stable_and_only_spawners_retain_pool():
    source = {
        "XAI_API_KEY": "primary",
        "XAI_API_KEY_2": "secondary",
        "RUNPOD_API_KEY": "gpu",
    }
    first = prepare_agent_secrets(source, "gtz-demo-attn-impl1", "implementer")
    again = prepare_agent_secrets(source, "gtz-demo-attn-impl1", "implementer")
    orchestrator = prepare_agent_secrets(source, "gtz-demo-attn-orchestrator", "team")

    assert first == again
    assert first["XAI_API_KEY"] in {"primary", "secondary"}
    assert "XAI_API_KEY_2" not in first
    assert "GTZ_XAI_KEY_POOL" not in first
    assert first["GTZ_XAI_KEY_SLOT"] in {"1", "2"}
    assert json.loads(orchestrator["GTZ_XAI_KEY_POOL"]) == ["primary", "secondary"]
    assert orchestrator["XAI_API_KEY"] in {"primary", "secondary"}


async def test_spawn_balances_xai_slots_in_registry_labels():
    client = FakeSandboxClient()
    source = {"XAI_API_KEY": "primary", "XAI_API_KEY_2": "secondary"}

    for index in range(4):
        await spawn_agent(
            CFG,
            client,
            team="attn",
            agent=f"impl{index}",
            role="implementer",
            brief="x",
            extra_envs=source,
        )

    slots = [meta.labels["gtz-xai-slot"] for meta in client.sandboxes.values()]
    assert slots.count("1") == 2
    assert slots.count("2") == 2
