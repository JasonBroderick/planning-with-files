---
name: pwf
description: "Create or resume a planning-with-files session by binding the current Hermes session to a named workspace and maintaining task_plan.md, findings.md, and progress.md. Use when the user invokes /pwf, asks to run PWF inside a workspace, or wants to resume a file-backed project plan."
version: 1.1.0
author: Hermes Agent
license: MIT
compatibility: hermes-agent
allowed-tools:
  - planning_with_files_bind_project
  - planning_with_files_init
  - planning_with_files_status
  - planning_with_files_check_complete
  - read_file
  - search_files
  - terminal
metadata:
  hermes:
    tags: [pwf, planning-with-files, planning, task_plan, resume]
    related_skills: [planning-with-files, pwf-auto]
---

# PWF

## Overview

`pwf` is the session-binding front door for the canonical `planning-with-files` workflow. The intended chat command is:

```text
/pwf run pwf inside <workspace>
```

Treat the text after `inside` as a workspace label. Strip optional braces, resolve it case-insensitively against configured PWF project roots, bind this Hermes session to the matching project, then initialize or resume its plan files.

The canonical workflow is installed at:

```text
${HERMES_HOME:-$HOME/.hermes}/skills/planning-with-files/SKILL.md
```

The three planning files are working memory on disk, so project state survives context compaction, `/clear`, gateway restarts, and interrupted work.

Design pattern: Router.

## Steps

### Step 1: load the canonical workflow

Read `${HERMES_HOME:-$HOME/.hermes}/skills/planning-with-files/SKILL.md` and follow its planning-file rules. If it is missing, stop and report that the canonical skill was not installed with the adapter.

### Step 2: resolve the workspace

For `/pwf run pwf inside <label>`:

1. Strip optional braces and surrounding whitespace.
2. Compare the label case-insensitively with directory basenames under the configured PWF project roots.
3. Prefer an exact basename match.
4. If exactly one match exists, use it immediately.
5. If several matches exist, ask one short disambiguation question.
6. If none exists, report the searched roots and do not guess.

Do not require an absolute path when one workspace matches unambiguously.

### Step 3: bind the session

Call `planning_with_files_bind_project` with the resolved absolute project root.

A successful response must identify the same project directory selected in Step 2. Stop on containment, missing-directory, or binding errors.

### Step 4: initialize or resume

Call `planning_with_files_init` without `cwd`. It preserves existing planning files and creates any missing member of the planning triple.

Then call `planning_with_files_status` without `cwd` and verify:

- `project_dir` is the selected workspace
- `plan_dir` is the intended root or active slug plan
- `task_plan.md`, `findings.md`, and `progress.md` are present
- the current phase and next action are readable

If the plan existed, read all three files before continuing. If it was created, populate its goal, phases, statuses, and `## Next Step` before execution begins.

### Step 5: keep planning state current

During work:

- record evidence and discoveries in `findings.md`
- record actions, test output, and failed attempts in `progress.md`
- update phase checklists and statuses in `task_plan.md`
- keep exactly one phase marked `in_progress`
- keep `## Next Step` to one concrete action

For autonomous execution of the active phase, use `pwf-auto` after binding.

## Error handling

| Failure | Response |
| --- | --- |
| Canonical skill missing | Stop and report the expected `$HERMES_HOME` path |
| No workspace match | Report the label and searched roots |
| Multiple workspace matches | Ask one disambiguation question |
| Binding rejected | Report the exact containment or path error |
| Planning files malformed | Preserve them, report the structural problem, and do not overwrite |
| Status resolves another project | Stop immediately and report the mismatch |

## Gotchas

- A tool-level `cd` does not change the long-running gateway process directory. Session binding is required.
- A subdirectory is not automatically the project root. Avoid creating duplicate planning triples.
- An active `.planning/<slug>/` plan can intentionally shadow a root plan.
- Status spelling is load-bearing: use `**Status:** in_progress` exactly.
- PWF autonomous markers alone do not schedule another Hermes turn. Use `pwf-auto`, which calls the plugin’s internal goal tools.
- Planning files are per-task working memory and may be gitignored. Durable product documentation still belongs in tracked project files.

See [references/hermes-discord-project-binding.md](references/hermes-discord-project-binding.md) for gateway architecture and verification details.

## Output format

```text
PWF: ready
project: /workspace/example
plan: /workspace/example/task_plan.md
action: resumed existing planning files
phase: Phase 2: Implementation
next: Run the focused integration tests.
```

## Verification checklist

- [ ] Workspace label resolved against configured roots
- [ ] Current session bound to the exact intended project
- [ ] Init and status called without `cwd` after binding
- [ ] Planning triple present and preserved
- [ ] Exactly one current phase identified
- [ ] `## Next Step` names one concrete action
- [ ] Output reports project, plan, phase, and next action
