# tests/test_bootstrap.py
from groktimizer.config import Budget, Caps, Config
from groktimizer.core.bootstrap import spawn_agent
from tests.fakes import FakeSandboxClient

CFG = Config(project="demo", shared_repo="git@x:y.git",
             tooling_repo="https://github.com/o/groktimizer.git",
             caps=Caps(), budget=Budget())


async def test_spawn_creates_configured_sandbox():
    client = FakeSandboxClient()
    name = await spawn_agent(CFG, client, team="attn", agent="impl1",
                             role="implementer", brief="Optimize softmax",
                             extra_envs={"RUNPOD_API_KEY": "k"})
    assert name == "gtz-demo-attn-impl1"
    meta = client.sandboxes[name]
    assert meta.labels["gtz-role"] == "implementer"
    # brief and setup script written into the sandbox
    assert "Optimize softmax" in client.files[(name, "/opt/gtz/brief.md")]
    setup = client.files[(name, "/opt/gtz/setup.sh")]
    assert "x.ai/cli/install.sh" in setup
    assert "tmux new-session" in setup
    # setup executed
    assert any("setup.sh" in cmd for _, cmd in client.execs)


async def test_hyphenated_names_rejected():
    import pytest
    from groktimizer.core.sandbox import InvalidNameError
    client = FakeSandboxClient()
    with pytest.raises(InvalidNameError):
        await spawn_agent(CFG, client, team="attn-opt", agent="a1",
                          role="implementer", brief="x")


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
    await spawn_agent(cfg, client, team="hq", agent="reconciler",
                      role="reconciler", brief="merge it all")
    assert captured["GTZ_GROK_MODEL"] == "grok-4-max"


async def test_secrets_go_to_env_file_not_create_envs():
    client = FakeSandboxClient()
    captured = {}
    orig = client.create

    async def create(name, image, region, labels, envs):
        captured.update(envs)
        await orig(name, image, region, labels, envs)

    client.create = create
    name = await spawn_agent(CFG, client, team="attn", agent="impl2",
                             role="implementer", brief="x",
                             extra_envs={"RUNPOD_API_KEY": "sekret", "XAI_API_KEY": "x'y"})
    assert "RUNPOD_API_KEY" not in captured  # not in control-plane envs
    assert "XAI_API_KEY" not in captured
    env_file = client.files[(name, "/opt/gtz/.env")]
    assert "export RUNPOD_API_KEY=sekret" in env_file
    assert "x'\"'\"'y" in env_file  # shell-quoted
    assert any("chmod 600 /opt/gtz/.env" in cmd for _, cmd in client.execs)
    # setup script sources it with xtrace disabled and the tmux line sources it too
    setup = client.files[(name, "/opt/gtz/setup.sh")]
    assert setup.count("/opt/gtz/.env") >= 2
