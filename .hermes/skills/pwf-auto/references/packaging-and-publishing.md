# Packaging and publishing the Hermes PWF command workflow

Use this when changing the Hermes PWF plugin or either user-facing command skill.

## Artifact set

The usable workflow has four coordinated directories:

1. `.hermes/plugins/planning-with-files/`
2. `.hermes/skills/planning-with-files/`
3. `.hermes/skills/pwf/`
4. `.hermes/skills/pwf-auto/`

The plugin provides session binding, plan tools, lifecycle hooks, and internal standing-goal control. The `pwf` skill exposes workspace resolution and binding. The `pwf-auto` skill exposes autonomous single-phase execution. Shipping only the plugin leaves the intended user commands outside the distributable artifact.

## Portability checks

Before committing command skills:

- replace installation-specific absolute paths with `${HERMES_HOME:-$HOME/.hermes}` where appropriate
- remove user-specific workspace names and personal wording from examples
- include every referenced support file under `references/`, `templates/`, or `scripts/`
- avoid references to skills that are not bundled unless they are explicitly optional
- document installation and verification of all coordinated directories from the same commit

## Verification sequence

1. Run SkillCheck against both `pwf` and `pwf-auto`.
2. Add packaging tests that assert the skill files, referenced support files, key plugin tool names, and portable paths.
3. Run focused Hermes tests.
4. Run the full repository suite.
5. Commit implementation, skills, documentation, and tests together when they form one usable release unit.
6. Push the target branch.
7. Compare local and remote SHAs.
8. Fetch both skill files from raw GitHub URLs using the immutable commit SHA and require HTTP 200 plus non-empty content.

## Reporting rule

State separately whether the plugin code, internal tools, canonical skill, `pwf` skill, and `pwf-auto` skill are written, committed, pushed, and remotely verified. Never use “on GitHub” for a commit that exists only locally.
