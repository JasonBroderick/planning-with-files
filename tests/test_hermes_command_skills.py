import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = REPO_ROOT / ".hermes" / "skills"


class HermesCommandSkillPackagingTests(unittest.TestCase):
    def test_pwf_skill_is_packaged_and_portable(self):
        skill = (SKILLS_ROOT / "pwf" / "SKILL.md").read_text(encoding="utf-8")
        reference = SKILLS_ROOT / "pwf" / "references" / "hermes-discord-project-binding.md"

        self.assertIn("name: pwf", skill)
        self.assertIn("planning_with_files_bind_project", skill)
        self.assertIn("planning_with_files_init", skill)
        self.assertIn("${HERMES_HOME:-$HOME/.hermes}", skill)
        self.assertNotIn("/workspace/skills/productivity", skill)
        self.assertTrue(reference.is_file())
        self.assertIn("Live plugin file-parity probe", reference.read_text(encoding="utf-8"))
        for required_line in (
            "PWF: ready",
            "files: task_plan.md, findings.md, progress.md",
            "status: <complete> complete, <in_progress> in_progress, <pending> pending",
            "ready: session bound and planning context loaded",
            "user action: Run /pwf-auto to execute the active phase autonomously.",
        ):
            self.assertIn(required_line, skill)
        self.assertIn("Return exactly this structure", skill)

    def test_pwf_auto_skill_is_packaged_with_goal_tools(self):
        skill = (SKILLS_ROOT / "pwf-auto" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("name: pwf-auto", skill)
        self.assertIn("planning_with_files_start_auto", skill)
        self.assertIn("planning_with_files_stop_auto", skill)
        self.assertIn("The skill does not ask the user to set `/goal`", skill)
        self.assertIn("Step 0: verify the live adapter", skill)
        self.assertTrue((SKILLS_ROOT / "pwf-auto" / "references" / "packaging-and-publishing.md").is_file())

    def test_install_documentation_links_all_coordinated_skills(self):
        docs = (REPO_ROOT / "docs" / "hermes.md").read_text(encoding="utf-8")

        self.assertIn("for skill in planning-with-files pwf pwf-auto", docs)
        self.assertIn("$HERMES_HOME/skills/pwf", docs)
        self.assertIn("$HERMES_HOME/skills/pwf-auto", docs)


if __name__ == "__main__":
    unittest.main()
