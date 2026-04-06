# OpenClaw Coordination Hardening — Detailed Change Note

Date: 2026-04-06

## Summary

This change series hardens ClawTeam-OpenClaw's nested OpenClaw worker coordination so real multi-agent rooms can converge reliably under OpenClaw 4.2-style exec allowlist behavior.

The repaired path was validated against an isolated `strategy-room` run where worker startup, task state updates, inbox messaging, memo synthesis, and final leader recommendation all completed successfully.

## Problem Statement

A realistic multi-agent run exposed three distinct failure layers:

1. **Shared runtime drift**
   - Parent and child workers were not guaranteed to operate against the same ClawTeam data directory.
   - Result: spawned workers could update a different task/inbox world than the leader was observing.

2. **Nested allowlist friction**
   - Even when the `clawteam` binary path itself was allowlisted, child workers could still trigger `exec denied: allowlist miss` if they emitted shell wrappers or chained commands such as `sleep`, `set -e`, `&&`, or `;`.
   - Result: agent coordination loops stalled or degraded unpredictably.

3. **Template-level convergence noise**
   - The `strategy-room` template already creates canonical tasks, but the leader guidance still encouraged creating another round of specialist tasks.
   - Result: the main workflow could succeed while redundant pending tasks remained on the board, making the room look unfinished.

## What Changed

### 1) Shared team data-dir propagation

The shared `CLAWTEAM_DATA_DIR` is now propagated into spawned OpenClaw workers so parent and child workers coordinate against the same task and inbox store.

Touched areas:
- `clawteam/spawn/tmux_backend.py`
- `clawteam/spawn/subprocess_backend.py`

### 2) Explicit `--data-dir` in prompt-generated coordination commands

Prompt-generated coordination commands now carry explicit `--data-dir` values for task and inbox operations, for example:

- `clawteam --data-dir <same-dir> task list ...`
- `clawteam --data-dir <same-dir> task update ...`
- `clawteam --data-dir <same-dir> inbox send ...`

Touched areas:
- `clawteam/spawn/prompt.py`
- `clawteam/cli/commands.py`

### 3) Allowlist-safe coordination posture

Prompt guidance was tightened so nested workers avoid brittle shell packaging that commonly triggers allowlist misses. Workers are now guided to:

- prefer one direct `clawteam` command per action
- avoid shell wrappers and chained forms like `sleep`, `set -e`, `&&`, and `;`
- wait by re-checking coordination primitives such as `task list`, `inbox peek`, and `inbox log`

This changes the expected coordination behavior from shell-driven waiting to state-driven polling.

### 4) Recoverability from local OpenClaw sessions/logs

Fallback recovery helpers were added so useful worker output can still be surfaced when task state lags behind actual worker progress.

New capabilities include:
- scanning local OpenClaw session JSONL files
- extracting latest assistant text from nested worker sessions
- tailing relevant OpenClaw logs
- summarizing recovered outputs alongside pending task state
- `runtime recover-openclaw` for explicit recovery

Touched area:
- `clawteam/cli/commands.py`

### 5) Strategy-room convergence hardening

The `strategy-room` template was updated so:

- the leader reuses canonical template tasks by default
- duplicate specialist tasks are not created unless a real gap exists
- if a genuinely new follow-up task is created, it must be completed, clearly reassigned, or intentionally deferred before the leader finishes
- the decision-editor uses a `peek -> receive -> provisional memo if still incomplete` flow instead of blocking forever

Touched area:
- `clawteam/templates/strategy-room.toml`

## Validation

### Regression tests

Validated with:
- `tests/test_prompt.py`
- `tests/test_spawn_backends.py`
- `tests/test_spawn_workspace_fallback.py`
- `tests/test_workspace_git.py`
- `tests/test_strategy_room_template.py`

Final local test result:
- **56 passed**

### End-to-end validation

An isolated `strategy-room` run confirmed:
- worker startup succeeds
- task states move through real transitions
- inbox send/peek/receive works between specialists, editor, and leader
- decision-editor successfully delivers a memo upstream
- strategy-lead reaches a final recommendation and marks the lead task completed

Observed outcome:
- the main coordination bug is fixed
- the previous blocker "task list/update plus inbox send complete end-to-end" is satisfied
- remaining issues are optimization-level template/runtime polish rather than emergency repair

## User-visible Impact

After this patch series, OpenClaw-backed ClawTeam rooms should be materially more reliable in realistic multi-agent runs:

- fewer false-stalled rooms
- fewer nested allowlist misses caused by shell-shaped coordination commands
- better odds of receiving a usable result even when some worker state lags
- cleaner board state at room completion

## Related commits

- `48be457 fix: harden openclaw team coordination fallbacks`
- `0acad67 fix: avoid duplicate strategy-room follow-up tasks`
