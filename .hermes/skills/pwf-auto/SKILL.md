---
name: pwf-auto
description: "Execute the active phase of a session-bound planning-with-files project through Hermes internal standing-goal continuation. Use when the user invokes /pwf-auto or asks Hermes to autonomously complete the next documented PWF phase without manually setting /goal."
version: 2.2.0
author: Hermes Agent
license: MIT
compatibility: hermes-agent
allowed-tools:
  - planning_with_files_status
  - planning_with_files_start_auto
  - planning_with_files_stop_auto
  - planning_with_files_check_complete
  - read_file
  - patch
  - write_file
  - terminal
metadata:
  hermes:
    tags: [pwf, autonomous, phases, goal, planning-with-files]
    related_skills: [pwf, planning-with-files, pwf-doctor]
---

# PWF Auto

## Overview

This pipeline executes exactly one phase from the project bound by `pwf`. The user-facing command is:

```text
/pwf-auto
```

The skill does not ask the user to set `/goal`. The PWF plugin creates the Hermes standing goal internally for the current session, arms PWF autonomous mode, and derives the goal text from the active plan and phase. At the end of each agent turn, Hermes sees that persisted goal and schedules the next turn automatically.

When the phase is verified complete or genuinely blocked, the skill calls the internal stop tool. That disarms PWF autonomous mode and marks the internal standing goal done. It does not automatically begin another phase. The user can review the result and invoke `/pwf-auto` again for the next phase.

Design pattern: Pipeline.

## Invocation contract

`/pwf-auto` requires a project already bound through `pwf`. It takes no required arguments.

The plugin is responsible for:

- resolving the current session's bound project
- resolving the active root or slug plan
- deriving the current incomplete phase
- generating a fresh 16-hex nonce
- writing and verifying the SHA-256 plan attestation
- resetting stale gate counters
- writing `.mode` last so failed arming cannot leave a partially active run
- activating Hermes `GoalManager` with the configured turn budget
- inheriting Hermes core's `DEFAULT_MAX_TURNS` when `goals.max_turns` is absent
- installing a PWF-scoped goal-budget bridge that disarms autonomous controls on exhaustion
- rolling back PWF control files if goal activation fails

## Pipeline

### Step 0: verify the live adapter after an update

If plugin Python files changed since the last successful `/pwf-auto` run, do not rely on the manifest version alone. Confirm the live plugin contains every repository module, import the live package in a fresh Hermes Python process, and complete a session-bound status call before starting autonomous mode. Per-file symlink deployments must explicitly add newly introduced modules. Restart only after this preflight passes.

### Step 1: inspect bound PWF state

Call `planning_with_files_status` without `cwd`.

Expected output:

- `project_dir` identifies the exact bound workspace
- `plan_dir` identifies the active root or slug plan
- planning files exist
- the current phase is named
- the plan is not already complete

Failure response:

- If no project is bound, stop and tell the user to run `pwf` for the intended workspace.
- If planning files do not exist, stop and tell the user to initialize through `pwf`.
- If the plan is malformed or has no executable phase, use `pwf-doctor` or report the exact structural issue.

### Step 2: start internal autonomous continuation

Call `planning_with_files_start_auto` with no arguments unless the user explicitly supplied a turn budget.

Expected output:

```json
{
  "ok": true,
  "goal_active": true,
  "project_dir": "/workspace/example",
  "plan_dir": "/workspace/example",
  "phase": "Phase 3: Implementation",
  "max_turns": 50,
  "mode": "autonomous"
}
```

The numeric budget shown above is illustrative. The tool reports the active `goals.max_turns` value from Hermes configuration, or Hermes core's own `DEFAULT_MAX_TURNS` when that key is absent. The tool sets the standing goal internally. Do not ask the user to invoke another command and do not create a cron job or secondary Hermes process.

Failure response: stop before execution and report the tool's exact error. A failed start must leave the previous PWF control state intact.

### Step 3: execute the phase

Read `task_plan.md`, `findings.md`, and `progress.md` from `plan_dir`. Identify the checklist, expected outputs, verification requirements, and `## Next Step` for the active phase.

For every work cycle:

1. Take the next concrete action in the active phase.
2. Verify the result using real tool output.
3. Record discoveries, evidence, and failed attempts in `findings.md`.
4. Record completed actions and verification in `progress.md`.
5. Update `task_plan.md` immediately when checklist or phase state changes.
6. Continue while executable work remains.

A routine progress message is not a stop condition. The internal Hermes goal supplies the next turn after the current response.

### Step 4: verify phase completion

Before declaring the phase complete:

1. Check every checklist item in that phase.
2. Run the phase's stated tests, acceptance checks, or evidence probes.
3. Update the phase status to `complete` only after verification passes.
4. Update `## Current Phase` and `## Next Step` so the plan points to the next pending phase without starting it.
5. Call `planning_with_files_check_complete` to record whether the whole plan is also complete.

If verification fails, keep the current phase `in_progress` and continue with a changed strategy.

### Step 5: stop the internal loop

When the active phase is complete, call:

```text
planning_with_files_stop_auto
```

Pass a concise reason that names the completed phase and its verification evidence. The tool disarms PWF mode and marks the internal standing goal done.

If a genuine external blocker requires user input, record it in both PWF files and call the same stop tool with the blocker as the reason. Do not leave a blocked autonomous goal running.

If the standing-goal budget is exhausted before completion, the plugin preserves the paused goal and incomplete planning files, disarms `.mode`, `.nonce`, `.stop_blocks`, and `.gate_last_ledger`, preserves the plan attestation, and replaces Hermes's `/goal resume` notice with an instruction to run `/pwf-auto`. A later `/pwf-auto` invocation re-arms the same incomplete phase with a fresh bounded budget. The plugin never renews the budget silently.

## Stop conditions

Stop only when one of these is true:

- the active phase is verified complete
- a genuine external dependency requires user input
- the same action fails twice with no new evidence or changed strategy
- the internal Hermes turn budget is exhausted
- the user interrupts the run

A stopped phase is not permission to start the next phase automatically.

## Anti-patterns

| Do not | Do instead |
| --- | --- |
| Ask the user to run `/goal` | Call `planning_with_files_start_auto` internally |
| Require arguments for `/pwf-auto` | Derive project and phase from the session binding and plan |
| Start a cron loop | Use Hermes's native standing-goal continuation |
| Continue into the next phase | Stop after the selected phase and wait for another `/pwf-auto` |
| Leave `.mode` active after completion | Call `planning_with_files_stop_auto` |
| Leave `.mode` active after budget exhaustion | Let the installed goal-budget bridge disarm controls and direct continuation through `/pwf-auto` |
| Silently renew an exhausted goal budget | Pause safely and require a new `/pwf-auto` invocation |
| Retry an unchanged failure indefinitely | Change strategy once, then stop with evidence if still blocked |

## Error handling

Fail fast and report for missing binding, missing plan, malformed phase state, arming failure, attestation failure, or goal-storage failure. The start tool performs transactional rollback if activation fails.

For execution failures, make one evidence-based strategy change and retry. Stop after a second unchanged failure and record the exact blocker.

## Output format

Start output:

```text
PWF auto: started
project: /workspace/example
phase: Phase 3: Implementation
continuation: active internally
turn budget: <configured goals.max_turns>
```

Completion output:

```text
PWF auto: phase complete
project: /workspace/example
phase: Phase 3: Implementation
verification: 128 tests passed
next phase: Phase 4: Acceptance
internal continuation: stopped
```

Blocked output:

```text
PWF auto: blocked
project: /workspace/example
phase: Phase 3: Implementation
blocker: required production credential is unavailable
needed: credential access
internal continuation: stopped
```

## Distribution contract

The two-command experience is not portable if only the Python plugin is committed. A distributable Hermes package must keep the canonical `planning-with-files` skill, `pwf`, `pwf-auto`, and the plugin together at one repository commit.

When changing this workflow:

1. Include both user-facing skills and all support files in the repository.
2. Replace installation-specific paths and personal examples before publishing.
3. Update installation documentation for all coordinated directories.
4. Add packaging tests for skill presence, portable paths, and required internal tool names.
5. Run SkillCheck for both command skills and the full repository suite.
6. Push the branch, compare local and remote SHAs, and fetch both remote skill files by immutable commit SHA before claiming they are on GitHub.

See [references/packaging-and-publishing.md](references/packaging-and-publishing.md) for the artifact map and release verification sequence.

## Gotchas

- `/pwf-auto` operates on the session binding, not the gateway process directory.
- The phase named under `## Current Phase` should agree with the phase carrying `**Status:** in_progress`.
- Root plans use `.plan-attestation`; slug plans use `.attestation`. The plugin derives the correct location.
- Intentional `task_plan.md` edits change the attested hash. The active PWF hook and plugin must treat recorded plan updates as intentional state changes.
- Hermes's goal budget is finite and inherited from `goals.max_turns`, falling back to Hermes core's own default. Exhaustion pauses the goal, disarms PWF autonomous controls, preserves the incomplete phase, and routes continuation through `/pwf-auto` rather than `/goal resume`.
- The skill completes one phase per invocation, even when the whole plan contains additional pending phases.

## Verification checklist

- [ ] Session resolves to the intended bound project
- [ ] Active plan and phase are derived without user arguments
- [ ] Internal start tool reports `goal_active: true`
- [ ] PWF mode, nonce, and attestation are armed successfully
- [ ] Phase work uses real verification output
- [ ] Findings and progress contain evidence and failed attempts
- [ ] Phase status changes only after verification
- [ ] Next phase is documented but not started
- [ ] Internal stop tool is called on completion or blocker
- [ ] PWF autonomous mode is disarmed before the final response
- [ ] User needed only `/pwf` and `/pwf-auto`
