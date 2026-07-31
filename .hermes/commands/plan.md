---
description: "Bind this Hermes session to a project and start or resume planning-with-files."
---

Load the `planning-with-files` skill and follow it.

1. Determine the actual project root for the current task.
2. Run `planning_with_files_bind_project` with `cwd` set to that project root. Never supply a session ID; Hermes provides it to the tool handler.
3. Run `planning_with_files_init` without `cwd` so it uses the new session binding. Existing files must not be replaced.
4. Run `planning_with_files_status` without `cwd`.
5. Read `task_plan.md`, `findings.md`, and `progress.md` from the bound project.
6. Begin or continue the single action under `## Next Step`.

Running this command again with another project root switches only the current Hermes session. It does not change other sessions or delete planning files.
