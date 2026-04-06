from __future__ import annotations

from typer.testing import CliRunner

from clawteam.cli.commands import app
from clawteam.team.manager import TeamManager
from clawteam.workspace.git import GitError


class FakeBackend:
    def __init__(self):
        self.calls: list[dict] = []

    def spawn(self, **kwargs):
        self.calls.append(kwargs)
        return "Agent 'worker' spawned"

    def list_running(self):
        return []


class FailingWorkspaceManager:
    def create_workspace(self, team_name: str, agent_name: str, agent_id: str):
        raise GitError("git worktree add ... invalid reference: main")


def test_spawn_auto_workspace_failure_falls_back_to_no_workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")

    backend = FakeBackend()
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: backend)
    monkeypatch.setattr("clawteam.workspace.get_workspace_manager", lambda repo=None: FailingWorkspaceManager())

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "spawn",
            "tmux",
            "openclaw",
            "--team",
            "demo",
            "--agent-name",
            "worker",
            "--task",
            "fix it",
        ],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path / "data")},
    )

    assert result.exit_code == 0
    assert "Workspace auto-disabled" in result.output
    assert backend.calls
    assert backend.calls[0]["cwd"] is None
