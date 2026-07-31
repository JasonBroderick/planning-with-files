# Hermes Setup

This repository ships a Hermes adapter for persistent planning, session-scoped project selection, and structure-aware plan injection.

The adapter has two parts:

- `.hermes/skills/planning-with-files/` contains the Hermes workflow skill and its bundled templates and scripts.
- `.hermes/plugins/planning-with-files/` contains the plugin that provides planning tools and lifecycle hooks.

Install both from the same repository commit. The plugin executes the canonical smart injector from the skill bundle, so mixing versions can produce inconsistent behavior.

## What the Adapter Provides

- `planning_with_files_bind_project` binds the current Hermes session to one project directory.
- `planning_with_files_unbind_project` removes only the current session's binding.
- `planning_with_files_init` creates `task_plan.md`, `findings.md`, and `progress.md` without replacing existing files.
- `planning_with_files_status` summarizes the bound or explicitly selected project.
- `planning_with_files_start_auto` transactionally arms the active plan and activates a Hermes standing goal for its current phase.
- `planning_with_files_stop_auto` disarms autonomous mode and marks the internal phase goal done.
- `planning_with_files_check_complete` runs the canonical completion check.
- `pre_llm_call` injects Goal, Next Step, Current Phase, the active phase, recent decisions, and recent progress through canonical `inject-plan.sh` smart mode.
- `post_tool_call` queues session-scoped planning reminders after write-like tools.

A Hermes session has at most one active PWF project. Different sessions may bind different projects concurrently, and one session may switch projects at any time.

## Recommended Install for Messaging Gateways

A user-profile installation is recommended when Hermes runs through Discord, Telegram, or another long-running gateway. It does not depend on the gateway process working directory.

### 1. Clone a maintained fork or source checkout

```bash
export PWF_REPO="${PWF_REPO:-$HOME/src/planning-with-files}"
export PWF_FORK_URL="${PWF_FORK_URL:-git@github.com:YOUR_ACCOUNT/planning-with-files.git}"

git clone "$PWF_FORK_URL" "$PWF_REPO"
git -C "$PWF_REPO" remote add upstream \
  https://github.com/OthmanAdi/planning-with-files.git
```

If the checkout already has an `upstream` remote, do not add it again.

### 2. Link the plugin and skill into the Hermes profile

Absolute symlinks make the Git checkout the single source of truth. They avoid copied installations that drift from the fork.

```bash
export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
export PWF_REPO="${PWF_REPO:-$HOME/src/planning-with-files}"

PWF_REPO="$(cd "$PWF_REPO" && pwd -P)"

test -f "$PWF_REPO/.hermes/plugins/planning-with-files/plugin.yaml"
test -f "$PWF_REPO/.hermes/skills/planning-with-files/SKILL.md"

mkdir -p "$HERMES_HOME/plugins" "$HERMES_HOME/skills"

for target in \
  "$HERMES_HOME/plugins/planning-with-files" \
  "$HERMES_HOME/skills/planning-with-files"
do
  if [ -e "$target" ] || [ -L "$target" ]; then
    printf 'Refusing to replace existing path: %s\n' "$target" >&2
    exit 1
  fi
done

ln -s \
  "$PWF_REPO/.hermes/plugins/planning-with-files" \
  "$HERMES_HOME/plugins/planning-with-files"

ln -s \
  "$PWF_REPO/.hermes/skills/planning-with-files" \
  "$HERMES_HOME/skills/planning-with-files"
```

The refusal check is intentional. Inspect and back up any previous copied installation before replacing it.

### 3. Configure allowed project roots

Remote sessions may bind only directories inside allowed roots. Separate multiple roots with the operating system path separator.

POSIX example:

```bash
export PWF_HERMES_PROJECT_ROOTS="$HOME/projects:/workspace"
```

If this variable is unset, the plugin checks a profile-writable roots file at:

```text
${PWF_HERMES_PROJECT_ROOTS_FILE:-${PWF_HERMES_STATE_DIR:-${HERMES_HOME:-$HOME/.hermes}/state/planning-with-files}/project-roots}
```

The file accepts one absolute project root per line. Empty lines and lines beginning with `#` are ignored. This is useful when a service manager does not expose custom environment variables.

Example:

```text
# Project workspaces
/home/user/projects
/workspace
```

If neither the environment variable nor roots file is configured, the plugin permits projects under the gateway process working directory and the Hermes home directory.

Optional state location:

```bash
export PWF_HERMES_STATE_DIR="$HERMES_HOME/state/planning-with-files"
```

The state directory and database are created with private permissions where the operating system supports POSIX mode bits.

Place persistent environment settings in the same environment source used by the Hermes gateway service or container. A shell-only export does not affect an already running gateway.

### 4. Enable the plugin and restart Hermes

```bash
hermes plugins enable planning-with-files
hermes gateway restart
```

For a foreground gateway or container, restart that process through its normal supervisor instead.

### 5. Verify the profile installation

```bash
test "$(readlink -f "$HERMES_HOME/plugins/planning-with-files")" = \
  "$PWF_REPO/.hermes/plugins/planning-with-files"

test "$(readlink -f "$HERMES_HOME/skills/planning-with-files")" = \
  "$PWF_REPO/.hermes/skills/planning-with-files"

hermes plugins list --plain --no-bundled
python3 -m unittest \
  "$PWF_REPO/tests/test_hermes_adapter.py" \
  "$PWF_REPO/tests/test_hermes_session_projects.py"
```

The plugin list should report `planning-with-files` as an enabled user plugin.

## Container Bind-Mount Install

A symlink inside a container cannot reach a source path that exists only on the host. Use bind mounts for container deployments.

```yaml
services:
  hermes:
    environment:
      PWF_HERMES_PROJECT_ROOTS: /workspace
      PYTHONDONTWRITEBYTECODE: "1"
    volumes:
      - type: bind
        source: ${PWF_REPO}/.hermes/plugins/planning-with-files
        target: /opt/hermes/plugins/planning-with-files
        read_only: true
      - type: bind
        source: ${PWF_REPO}/.hermes/skills/planning-with-files
        target: /opt/hermes/skills/planning-with-files
        read_only: true
      - type: bind
        source: ${PROJECTS_ROOT}
        target: /workspace
```

Adjust `/opt/hermes` to the container's actual `HERMES_HOME`. Mount the state directory on persistent storage if the container filesystem is ephemeral.

## Project-Local Alternative

A project-local plugin remains appropriate when the adapter should load for only one repository.

```bash
export HERMES_ENABLE_PROJECT_PLUGINS=1
```

Start Hermes from that repository. This route is less suitable for a long-running messaging gateway because plugin discovery depends on the gateway environment and working directory.

## Using Projects from Chat

### Start or resume a project

Use the `pwf` skill command with a workspace label:

```text
/pwf run pwf inside Oracle
```

The skill resolves the label against allowed PWF roots, then calls `planning_with_files_bind_project`, `planning_with_files_init`, and `planning_with_files_status`. Existing planning files are preserved and resumed. The user does not need to know the absolute workspace path when the label has one unambiguous match.

### Run the active phase autonomously

After the workspace is bound, use:

```text
/pwf-auto
```

The skill calls `planning_with_files_start_auto` without requiring user arguments. The plugin derives the active phase, arms mode, nonce, counters, and plan attestation transactionally, then persists an active Hermes `GoalManager` record for the current session. The gateway detects that goal at the end of the same turn and queues continuation turns automatically.

The run stops after the selected phase, not after the entire plan. On verified completion or a genuine blocker, the skill calls `planning_with_files_stop_auto`, which disarms PWF mode and marks the internal goal done. The user does not need to invoke `/goal` directly.

### Switch the current session

```text
Switch planning-with-files to /absolute/path/to/another-project and resume it.
```

Rebinding replaces only the current session's active project. Other sessions keep their bindings.

### Stop automatic planning context in the current session

```text
Unbind planning-with-files from this session.
```

This does not delete or modify any project files.

### Multiple projects at once

Concurrent sessions are isolated:

```text
session A -> project A
session B -> project B
session C -> project C
```

Two sessions may intentionally bind the same project, but concurrent writes can conflict. Coordinate work packages when sharing one planning triple.

## How Session State Works

Bindings are stored in SQLite at:

```text
${PWF_HERMES_STATE_DIR:-${HERMES_HOME:-$HOME/.hermes}/state/planning-with-files}/bindings.sqlite3
```

The database stores only:

- a SHA-256 digest of the opaque Hermes session identity
- a SHA-256 digest of the configured allowed root
- the project path relative to that root

It does not store raw session IDs, platform IDs, user IDs, messages, conversation history, model names, or absolute allowed-root paths.

A binding is checked against the current allowed roots on every lookup. Deleted projects, changed roots, and symlink escapes fail closed and inject no project context.

## Smart Context Injection

The Hermes hook runs the canonical helper:

```bash
PWF_INJECT=smart sh inject-plan.sh --context=userprompt
```

The helper selects relevant plan data instead of the first N lines:

- title
- Goal
- Next Step
- Current Phase
- phase count
- complete active phase body
- last three decisions
- recent progress or ledger summary

A successful empty result is respected. This preserves `PLANNING_DISABLED=1`, containment checks, and other canonical decisions.

Smart context defaults to 65,536 bytes. Override the bound with:

```bash
export PWF_HERMES_MAX_CONTEXT_BYTES=65536
```

Values are clamped between 4,096 bytes and 1 MiB. Truncated output receives an explicit marker and a matching closing plan-data delimiter.

The plugin uses its legacy plan-head and progress-tail context only when the helper or POSIX `sh` is unavailable. Timeouts and unexpected execution failures fail closed instead of bypassing the canonical security behavior.

The write reminder is session-scoped. A write-like tool call queues a reminder for the bound session, but the plugin does not rewrite or redirect the tool's file path.

## Updating a Maintained Fork

Do not edit the profile symlinks. Update the source checkout and merge upstream into the adaptation branch.

Require a clean tree first:

```bash
export PWF_REPO="${PWF_REPO:-$HOME/src/planning-with-files}"
export PWF_BRANCH="${PWF_BRANCH:-hermes-adapter}"

test -z "$(git -C "$PWF_REPO" status --porcelain)" || {
  printf '%s\n' 'Refusing to update: commit or stash changes first.' >&2
  exit 1
}
```

Fetch upstream and create a rollback branch:

```bash
git -C "$PWF_REPO" fetch upstream --prune --tags
git -C "$PWF_REPO" switch "$PWF_BRANCH"

BACKUP_BRANCH="backup/${PWF_BRANCH}-$(date -u +%Y%m%dT%H%M%SZ)"
git -C "$PWF_REPO" branch "$BACKUP_BRANCH"
printf 'Rollback branch: %s\n' "$BACKUP_BRANCH"
```

Merge without rewriting local adaptation commits:

```bash
git -C "$PWF_REPO" merge --no-edit upstream/master
```

Resolve any conflict deliberately, then run:

```bash
python3 -m unittest \
  "$PWF_REPO/tests/test_hermes_adapter.py" \
  "$PWF_REPO/tests/test_hermes_session_projects.py"

python3 -m pytest "$PWF_REPO/tests/" -q
python3 "$PWF_REPO/scripts/sync-ide-folders.py" --verify
```

Restart Hermes only after validation passes:

```bash
hermes gateway restart
hermes plugins list --plain --no-bundled
```

Do not run `hermes plugins update planning-with-files` for a symlink or bind-mount installation. Git controls the source checkout.

### Abort or roll back an update

Before completing a merge:

```bash
git -C "$PWF_REPO" merge --abort
```

After a completed but unsuccessful update, restore the rollback branch only if the working tree is clean and the branch was created by the procedure above:

```bash
git -C "$PWF_REPO" reset --hard "$BACKUP_BRANCH"
hermes gateway restart
```

## Removing a Symlink Installation

Remove only verified symlinks:

```bash
export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

for target in \
  "$HERMES_HOME/plugins/planning-with-files" \
  "$HERMES_HOME/skills/planning-with-files"
do
  if [ -L "$target" ]; then
    rm "$target"
  else
    printf 'Refusing to remove non-symlink path: %s\n' "$target" >&2
    exit 1
  fi
done

hermes gateway restart
```

This removes the profile links. It does not delete the source checkout, project files, or binding database.

## Validation

Focused Hermes QA:

```bash
python3 -m unittest \
  tests/test_hermes_adapter.py \
  tests/test_hermes_session_projects.py
```

Full repository QA:

```bash
python3 -m pytest tests/ -q
python3 scripts/sync-ide-folders.py --verify
```

## Platform Notes

- The adapter uses Hermes lifecycle hooks, but completion enforcement remains advisory rather than a native stop gate.
- Smart injection requires POSIX `sh`. Installations without it use legacy context extraction.
- Deliberate creation of a new Hermes session produces a new opaque session identity and therefore requires rebinding the desired project.
- Gateway restart normally preserves persisted bindings because the session identity remains stable.
