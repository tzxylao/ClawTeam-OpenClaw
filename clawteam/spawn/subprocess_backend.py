"""Subprocess spawn backend - launches agents as separate processes."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from clawteam.spawn.base import SpawnBackend
from clawteam.spawn.cli_env import (
    build_spawn_path,
    propagate_openclaw_gateway_token,
    resolve_clawteam_executable,
)
from clawteam.spawn.command_validation import (
    command_has_workspace_arg,
    is_claude_command,
    is_codex_command,
    is_gemini_command,
    is_kimi_command,
    is_nanobot_command,
    is_openclaw_command,
    is_opencode_command,
    is_qwen_command,
    normalize_spawn_command,
    validate_spawn_command,
)


class SubprocessBackend(SpawnBackend):
    """Spawn agents as independent subprocesses running any command."""

    def __init__(self):
        self._processes: dict[str, subprocess.Popen] = {}

    def spawn(
        self,
        command: list[str],
        agent_name: str,
        agent_id: str,
        agent_type: str,
        team_name: str,
        prompt: str | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        skip_permissions: bool = False,
        openclaw_agent: str | None = None,
        model: str | None = None,
    ) -> str:
        if openclaw_agent:
            raise NotImplementedError(
                f"openclaw_agent is not supported with subprocess backend "
                f"(got {openclaw_agent!r}); use tmux backend instead."
            )

        spawn_env = os.environ.copy()
        clawteam_bin = resolve_clawteam_executable()
        spawn_env.update({
            "CLAWTEAM_AGENT_ID": agent_id,
            "CLAWTEAM_AGENT_NAME": agent_name,
            "CLAWTEAM_AGENT_TYPE": agent_type,
            "CLAWTEAM_TEAM_NAME": team_name,
            "CLAWTEAM_AGENT_LEADER": "0",
            "CLAWTEAM_MEMORY_SCOPE": f"custom:team-{team_name}",
        })
        # Propagate user if set
        user = os.environ.get("CLAWTEAM_USER", "")
        if user:
            spawn_env["CLAWTEAM_USER"] = user
        # Propagate transport if set
        transport = os.environ.get("CLAWTEAM_TRANSPORT", "")
        if transport:
            spawn_env["CLAWTEAM_TRANSPORT"] = transport
        data_dir = os.environ.get("CLAWTEAM_DATA_DIR", "")
        if data_dir:
            spawn_env["CLAWTEAM_DATA_DIR"] = data_dir
        if cwd:
            spawn_env["CLAWTEAM_WORKSPACE_DIR"] = cwd
        if model:
            spawn_env["CLAWTEAM_MODEL"] = model
        if env:
            spawn_env.update(env)
        spawn_env["PATH"] = build_spawn_path(spawn_env.get("PATH"))
        if os.path.isabs(clawteam_bin):
            spawn_env.setdefault("CLAWTEAM_BIN", clawteam_bin)
        if is_openclaw_command(command):
            propagate_openclaw_gateway_token(spawn_env)

        normalized_command = normalize_spawn_command(command)

        command_error = validate_spawn_command(normalized_command, path=spawn_env["PATH"], cwd=cwd)
        if command_error:
            return command_error

        final_command = list(normalized_command)
        if skip_permissions:
            if is_claude_command(normalized_command) or is_qwen_command(normalized_command):
                final_command.append("--dangerously-skip-permissions")
            elif is_codex_command(normalized_command):
                final_command.append("--dangerously-bypass-approvals-and-sandbox")
            elif is_gemini_command(normalized_command) or is_kimi_command(normalized_command) or is_opencode_command(normalized_command):
                final_command.append("--yolo")
        # Claude Code: pass --model if specified
        # NOTE: do NOT pass --model to OpenClaw here.
        # Current local OpenClaw `agent` CLI does not support `--model`, and
        # injecting it causes workers to exit immediately with:
        #   error: unknown option '--model'
        # Keep CLAWTEAM_MODEL in env for future compatibility / introspection,
        # but avoid CLI injection until the installed OpenClaw actually supports it.
        if model and is_claude_command(normalized_command):
            final_command.extend(["--model", model])
        if is_kimi_command(normalized_command):
            if cwd and not command_has_workspace_arg(normalized_command):
                final_command.extend(["-w", cwd])
            if prompt:
                final_command.extend(["--print", "-p", prompt])
        elif is_nanobot_command(normalized_command):
            if cwd and not command_has_workspace_arg(normalized_command):
                final_command.extend(["-w", cwd])
            if prompt:
                final_command.extend(["-m", prompt])
        elif prompt:
            if is_codex_command(normalized_command):
                final_command.append(prompt)
            elif is_openclaw_command(normalized_command):
                # OpenClaw agent mode: use --message for the prompt
                if "agent" not in final_command and "tui" not in final_command:
                    final_command.insert(1, "agent")
                # Ensure machine-readable output so subprocess workers can be
                # harvested from stdout logs even when clawteam CLI callbacks
                # are blocked by newer OpenClaw exec policy.
                if "--json" not in final_command:
                    final_command.append("--json")
                # Isolate each agent in its own session
                session_key = f"clawteam-{team_name}-{agent_name}"
                final_command.extend(["--session-id", session_key, "--message", prompt])
            else:
                final_command.extend(["-p", prompt])

        logs_dir = Path.home() / ".clawteam" / "teams" / team_name / "agent-logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = logs_dir / f"{agent_name}.stdout.log"
        stderr_path = logs_dir / f"{agent_name}.stderr.log"
        stdout_f = open(stdout_path, "ab")
        stderr_f = open(stderr_path, "ab")

        # Use raw argv execution instead of shell=True wrapping for OpenClaw
        # workers. Newer OpenClaw / Gateway combinations appear to lose or
        # reroute stdout/stderr when launched behind the previous shell+trap
        # wrapper, which breaks ClawTeam's ability to harvest worker output.
        # Prefer reliable output capture first; lifecycle cleanup can be
        # recovered separately if needed.
        process = subprocess.Popen(
            final_command,
            shell=False,
            env=spawn_env,
            stdout=stdout_f,
            stderr=stderr_f,
            cwd=cwd,
        )
        self._processes[agent_name] = process

        # Persist spawn info for liveness checking
        from clawteam.spawn.registry import register_agent
        register_agent(
            team_name=team_name,
            agent_name=agent_name,
            backend="subprocess",
            pid=process.pid,
            command=list(final_command) + [
                f"# stdout_log={stdout_path}",
                f"# stderr_log={stderr_path}",
            ],
        )

        return f"Agent '{agent_name}' spawned as subprocess (pid={process.pid})"

    def list_running(self) -> list[dict[str, str]]:
        result = []
        for name, proc in list(self._processes.items()):
            if proc.poll() is None:
                result.append({"name": name, "pid": str(proc.pid), "backend": "subprocess"})
            else:
                self._processes.pop(name, None)
        return result
