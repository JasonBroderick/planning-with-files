---
description: "Show planning-with-files status for this Hermes session's bound project."
---

Run `planning_with_files_status` without `cwd` so it resolves the current Hermes session binding. Present the result as a compact status summary with project directory, current phase, phase counts, and the single next action.

If no project is bound, ask the user for the project directory and call `planning_with_files_bind_project` before retrying status.
