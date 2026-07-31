# Hermes gateway project binding for Planning With Files

Use this reference when PWF runs through a long-lived Hermes gateway rather than a CLI launched from the project directory.

## Working-directory distinction

A terminal tool call with `cwd=/path/project`, or a shell command that runs `cd /path/project`, changes where that tool operates. It does not change the working directory of the long-running Hermes gateway process.

If a PWF hook resolves plans with `Path.cwd()`, prompt instructions to change directory are insufficient for automatic plan injection. Explicit session binding solves this problem.

## Session-binding design

1. Hermes tool handlers and lifecycle hooks receive an opaque `session_id`.
2. `planning_with_files_bind_project` validates a project inside configured roots and stores a session-scoped binding.
3. `planning_with_files_init`, `planning_with_files_status`, and completion tools resolve the bound project when `cwd` is omitted.
4. Bindings persist outside the plugin directory so plugin updates and gateway restarts do not erase them.
5. Hooks resolve the bound project first and fail closed for invalid or stale bindings.
6. Rebinding changes only the current session. Other sessions can remain attached to other projects.

This supports separate Discord or Telegram conversations bound to separate projects without changing the gateway process directory.

## Project roots

Configure one or more allowed roots using either:

- `PWF_HERMES_PROJECT_ROOTS`, separated by the operating system path separator
- `${PWF_HERMES_STATE_DIR:-${HERMES_HOME}/state/planning-with-files}/project-roots`, one absolute root per line

Do not claim readiness until a live bind proves the intended project is accepted.

## Smart injection

The plugin runs the canonical PWF injector in the bound plan directory:

```bash
PWF_INJECT=smart sh "$HERMES_HOME/skills/planning-with-files/scripts/inject-plan.sh"
```

Smart injection selects the title, Goal, Next Step, Current Phase, active phase, recent decisions, and recent progress within a bounded byte budget.

## Autonomous phase execution

Keep these capabilities distinct:

1. PWF control files such as mode, nonce, counters, and plan attestation.
2. A session-aware plugin tool that arms those controls.
3. A Hermes standing goal that schedules continuation turns while work remains.

`pwf-auto` combines all three through `planning_with_files_start_auto`. When the phase completes or blocks, it calls `planning_with_files_stop_auto` to disarm PWF and mark the standing goal done.

A marker written by a shell script is not sufficient by itself. Verify the registered plugin tools and prove a phase can continue without another user message.

## Safe rollout

- Install the plugin and all three Hermes skills from the same repository commit.
- Restart the gateway after changing plugin Python files.
- Do not restart while unrelated agent runs are active unless the gateway can drain them safely.
- Verify bindings, registered tool names, and focused tests after restart.
- Keep raw session and platform identifiers out of persistent PWF state.

## Verification probes

For a bound project, verify:

- status returns the exact expected `project_dir`
- injected context contains Goal, Next Step, Current Phase, and the `in_progress` phase
- two different sessions can resolve different projects
- a gateway restart preserves bindings
- unbinding fails closed rather than falling back to an unrelated gateway directory
- `planning_with_files_start_auto` and `planning_with_files_stop_auto` are registered
