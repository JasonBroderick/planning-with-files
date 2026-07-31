from __future__ import annotations

import importlib
import importlib.util
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / ".hermes" / "plugins" / "planning-with-files"
MODULE_PATH = PLUGIN_ROOT / "__init__.py"
PACKAGE_NAME = "planning_with_files_session_test_plugin"


def load_plugin():
    for name in list(sys.modules):
        if name == PACKAGE_NAME or name.startswith(PACKAGE_NAME + "."):
            del sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        MODULE_PATH,
        submodule_search_locations=[str(PLUGIN_ROOT)],
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


plugin = load_plugin()
bindings = importlib.import_module(PACKAGE_NAME + ".project_bindings")
hooks = importlib.import_module(PACKAGE_NAME + ".hooks")
tools = importlib.import_module(PACKAGE_NAME + ".tools")


class FakeContext:
    def __init__(self) -> None:
        self.tools = {}
        self.hooks = {}

    def register_tool(self, name, handler, **kwargs) -> None:
        self.tools[name] = handler

    def register_hook(self, name, handler) -> None:
        self.hooks[name] = handler


class HermesSessionProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.state_dir = self.root / "state"
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.env = mock.patch.dict(
            os.environ,
            {
                "PWF_HERMES_STATE_DIR": str(self.state_dir),
                "PWF_HERMES_PROJECT_ROOTS": str(self.workspace),
                "PLANNING_WITH_FILES_SKILL_ROOT": str(REPO_ROOT / "skills" / "planning-with-files"),
            },
            clear=False,
        )
        self.env.start()
        bindings.reset_store_cache()

    def tearDown(self) -> None:
        bindings.reset_store_cache()
        self.env.stop()
        self.tmp.cleanup()

    def make_project(self, name: str, marker: str, *, active: bool = True) -> Path:
        project = self.workspace / name
        project.mkdir(parents=True)
        status = "in_progress" if active else "pending"
        project.joinpath("task_plan.md").write_text(
            "# Test Plan\n\n"
            "## Goal\n\nDeliver " + marker + ".\n\n"
            "## Next Step\n\nContinue " + marker + ".\n\n"
            "## Current Phase\n\nPhase 2: " + marker + "\n\n"
            "## Phases\n\n"
            "### Phase 1: Completed setup\n"
            "**Status:** complete\n\n"
            + "\n".join("completed line %d" % i for i in range(60))
            + "\n\n### Phase 2: " + marker + "\n"
            "**Status:** " + status + "\n\n"
            "ACTIVE_" + marker + "\n\n"
            "## Decisions Made\n\n"
            "| Date | Decision |\n"
            "|------|----------|\n"
            "| 2026-01-01 | " + marker + " decision |\n",
            encoding="utf-8",
        )
        project.joinpath("progress.md").write_text("# Progress\n\nPROGRESS_" + marker + "\n", encoding="utf-8")
        project.joinpath("findings.md").write_text("# Findings\n\nFINDING_" + marker + "\n", encoding="utf-8")
        return project

    def bind(self, session_id: str, project: Path) -> dict:
        return json.loads(tools.planning_with_files_bind_project(cwd=str(project), session_id=session_id))

    def test_two_sessions_inject_only_their_bound_projects(self) -> None:
        project_a = self.make_project("project-a", "PLAN_A")
        project_b = self.make_project("project-b", "PLAN_B")
        self.assertTrue(self.bind("session-a", project_a)["ok"])
        self.assertTrue(self.bind("session-b", project_b)["ok"])

        payload_a = hooks.pre_llm_call(user_message="continue", session_id="session-a", platform="discord")
        payload_b = hooks.pre_llm_call(user_message="continue", session_id="session-b", platform="discord")

        assert payload_a is not None and payload_b is not None
        self.assertIn("PLAN_A", payload_a["context"])
        self.assertNotIn("PLAN_B", payload_a["context"])
        self.assertIn("PLAN_B", payload_b["context"])
        self.assertNotIn("PLAN_A", payload_b["context"])

    def test_rebinding_one_session_switches_only_that_session(self) -> None:
        project_a = self.make_project("project-a", "PLAN_A")
        project_b = self.make_project("project-b", "PLAN_B")
        self.bind("session-a", project_a)
        self.bind("session-b", project_a)
        self.bind("session-a", project_b)

        payload_a = hooks.pre_llm_call(user_message="continue", session_id="session-a", platform="discord")
        payload_b = hooks.pre_llm_call(user_message="continue", session_id="session-b", platform="discord")

        assert payload_a is not None and payload_b is not None
        self.assertIn("PLAN_B", payload_a["context"])
        self.assertNotIn("PLAN_A", payload_a["context"])
        self.assertIn("PLAN_A", payload_b["context"])

    def test_binding_survives_store_recreation(self) -> None:
        project = self.make_project("restart-project", "RESTART")
        self.bind("restart-session", project)
        bindings.reset_store_cache()
        resolved = bindings.resolve_bound_project("restart-session")
        self.assertEqual(project.resolve(), resolved)

    def test_concurrent_bindings_are_not_lost(self) -> None:
        projects = [self.make_project("project-%02d" % i, "PLAN_%02d" % i) for i in range(12)]
        barrier = threading.Barrier(len(projects))
        errors = []

        def worker(index: int) -> None:
            try:
                barrier.wait()
                result = self.bind("session-%02d" % index, projects[index])
                if not result.get("ok"):
                    errors.append(result)
            except Exception as exc:
                errors.append(repr(exc))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(projects))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual([], errors)
        bindings.reset_store_cache()
        for index, project in enumerate(projects):
            self.assertEqual(project.resolve(), bindings.resolve_bound_project("session-%02d" % index))

    def test_state_does_not_contain_raw_session_or_absolute_root(self) -> None:
        project = self.make_project("private-project", "PRIVATE")
        raw_session = "discord:guild-123:channel-456:user@example.test"
        self.bind(raw_session, project)
        state_bytes = b"".join(path.read_bytes() for path in self.state_dir.rglob("*") if path.is_file())
        self.assertNotIn(raw_session.encode(), state_bytes)
        self.assertNotIn(str(self.workspace).encode(), state_bytes)
        self.assertNotIn(b"guild-123", state_bytes)
        self.assertNotIn(b"channel-456", state_bytes)
        self.assertNotIn(b"user@example.test", state_bytes)

    @unittest.skipIf(os.name == "nt", "POSIX permission bits are not portable to Windows")
    def test_state_directory_and_database_are_private(self) -> None:
        project = self.make_project("permissions", "PERMISSIONS")
        self.bind("permissions-session", project)
        db_path = self.state_dir / "bindings.sqlite3"
        self.assertEqual(0, stat.S_IMODE(self.state_dir.stat().st_mode) & 0o077)
        self.assertEqual(0, stat.S_IMODE(db_path.stat().st_mode) & 0o077)

    def test_project_outside_allowed_roots_is_rejected_without_rebinding(self) -> None:
        valid = self.make_project("valid", "VALID")
        outside = self.root / "outside"
        outside.mkdir()
        outside.joinpath("task_plan.md").write_text("# Outside\n", encoding="utf-8")
        self.bind("session-a", valid)
        result = self.bind("session-a", outside)
        self.assertFalse(result["ok"])
        self.assertEqual(valid.resolve(), bindings.resolve_bound_project("session-a"))

    def test_symlink_escape_is_rejected(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        outside.joinpath("task_plan.md").write_text("# Outside\n", encoding="utf-8")
        link = self.workspace / "escaped"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest("symlinks unavailable: %s" % exc)
        result = self.bind("session-a", link)
        self.assertFalse(result["ok"])
        self.assertIsNone(bindings.resolve_bound_project("session-a"))

    def test_unbound_gateway_session_does_not_inherit_process_cwd_plan(self) -> None:
        gateway_project = self.make_project("gateway", "GATEWAY")
        old_cwd = Path.cwd()
        try:
            os.chdir(gateway_project)
            payload = hooks.pre_llm_call(
                user_message="continue",
                session_id="unbound-session",
                platform="discord",
            )
        finally:
            os.chdir(old_cwd)
        self.assertIsNone(payload)

    def test_cli_without_session_identity_preserves_cwd_behavior(self) -> None:
        cli_project = self.make_project("cli", "CLI_PLAN")
        old_cwd = Path.cwd()
        try:
            os.chdir(cli_project)
            payload = hooks.pre_llm_call(user_message="continue", session_id="", platform="")
        finally:
            os.chdir(old_cwd)
        assert payload is not None
        self.assertIn("CLI_PLAN", payload["context"])

    def test_smart_injection_includes_late_active_phase(self) -> None:
        project = self.make_project("smart", "SMART_PHASE")
        self.bind("smart-session", project)
        payload = hooks.pre_llm_call(
            user_message="continue",
            session_id="smart-session",
            platform="discord",
        )
        assert payload is not None
        self.assertIn("===BEGIN PLAN DATA===", payload["context"])
        self.assertIn("ACTIVE_SMART_PHASE", payload["context"])
        self.assertNotIn("completed line 59", payload["context"])

    def test_planning_disabled_does_not_fall_back_to_legacy_context(self) -> None:
        project = self.make_project("disabled", "DISABLED")
        self.bind("disabled-session", project)
        with mock.patch.dict(os.environ, {"PLANNING_DISABLED": "1"}, clear=False):
            payload = hooks.pre_llm_call(
                user_message="continue",
                session_id="disabled-session",
                platform="discord",
            )
        self.assertIsNone(payload)

    def test_missing_smart_injector_uses_legacy_context(self) -> None:
        project = self.make_project("legacy", "LEGACY")
        self.bind("legacy-session", project)
        empty_skill = self.root / "empty-skill"
        empty_skill.joinpath("scripts").mkdir(parents=True)
        empty_skill.joinpath("templates").mkdir()
        empty_skill.joinpath("scripts", "check-complete.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"PLANNING_WITH_FILES_SKILL_ROOT": str(empty_skill)}, clear=False):
            payload = hooks.pre_llm_call(
                user_message="continue",
                session_id="legacy-session",
                platform="discord",
            )
        assert payload is not None
        self.assertIn("ACTIVE PLAN", payload["context"])
        self.assertIn("LEGACY", payload["context"])

    def test_post_tool_reminder_uses_bound_project_not_gateway_cwd(self) -> None:
        project = self.make_project("bound", "BOUND")
        self.bind("bound-session", project)
        empty_gateway = self.root / "gateway-empty"
        empty_gateway.mkdir()
        old_cwd = Path.cwd()
        try:
            os.chdir(empty_gateway)
            hooks.post_tool_call(
                tool_name="write_file",
                session_id="bound-session",
                platform="discord",
                args={"path": str(project / "app.py"), "content": "x"},
            )
            payload = hooks.pre_llm_call(
                user_message="continue",
                session_id="bound-session",
                platform="discord",
            )
        finally:
            os.chdir(old_cwd)
        assert payload is not None
        self.assertIn("Update progress.md", payload["context"])
        self.assertIn("BOUND", payload["context"])

    def test_registered_bind_handler_uses_runtime_session_id(self) -> None:
        project = self.make_project("registered", "REGISTERED")
        ctx = FakeContext()
        plugin.register(ctx)
        handler = ctx.tools["planning_with_files_bind_project"]
        result = json.loads(handler({"cwd": str(project)}, session_id="trusted-session", platform="discord"))
        self.assertTrue(result["ok"])
        self.assertEqual(project.resolve(), bindings.resolve_bound_project("trusted-session"))

    def test_unbind_clears_only_current_session(self) -> None:
        project_a = self.make_project("project-a", "PLAN_A")
        project_b = self.make_project("project-b", "PLAN_B")
        self.bind("session-a", project_a)
        self.bind("session-b", project_b)
        result = json.loads(tools.planning_with_files_unbind_project(session_id="session-a"))
        self.assertTrue(result["ok"])
        self.assertIsNone(bindings.resolve_bound_project("session-a"))
        self.assertEqual(project_b.resolve(), bindings.resolve_bound_project("session-b"))
    def test_unbound_registered_status_fails_closed_without_platform_kwarg(self) -> None:
        gateway_project = self.make_project("gateway", "GATEWAY_SECRET")
        ctx = FakeContext()
        plugin.register(ctx)
        old_cwd = Path.cwd()
        try:
            os.chdir(gateway_project)
            result = json.loads(
                ctx.tools["planning_with_files_status"](
                    {},
                    session_id="unbound-real-handler",
                    task_id="unbound-real-handler",
                    user_task="show status",
                )
            )
        finally:
            os.chdir(old_cwd)
        self.assertFalse(result["ok"])
        self.assertNotIn("GATEWAY_SECRET", json.dumps(result))

    def test_explicit_cwd_is_contained_for_runtime_session(self) -> None:
        outside = self.root / "outside-explicit"
        outside.mkdir()
        outside.joinpath("task_plan.md").write_text("# OUTSIDE_SECRET\n", encoding="utf-8")
        result = json.loads(
            tools.planning_with_files_status(
                cwd=str(outside),
                session_id="remote-session",
            )
        )
        self.assertFalse(result["ok"])
        self.assertNotIn("OUTSIDE_SECRET", json.dumps(result))

    def test_scoped_plan_is_injected_without_root_task_plan(self) -> None:
        project = self.workspace / "scoped"
        plan = project / ".planning" / "2026-01-01-feature"
        plan.mkdir(parents=True)
        plan.joinpath("task_plan.md").write_text(
            "# Scoped Plan\n\n## Goal\n\nSCOPED_GOAL\n\n## Phases\n\n"
            "### Phase 1: Scoped work\n**Status:** in_progress\n\nSCOPED_ACTIVE\n",
            encoding="utf-8",
        )
        plan.joinpath("progress.md").write_text("SCOPED_PROGRESS\n", encoding="utf-8")
        project.joinpath(".planning", ".active_plan").write_text("2026-01-01-feature\n", encoding="utf-8")
        self.bind("scoped-session", project)
        payload = hooks.pre_llm_call(
            user_message="continue",
            session_id="scoped-session",
            platform="discord",
        )
        assert payload is not None
        self.assertIn("SCOPED_GOAL", payload["context"])
        self.assertIn("SCOPED_ACTIVE", payload["context"])

    def test_smart_context_is_bounded_and_marked_when_truncated(self) -> None:
        project = self.make_project("large", "LARGE")
        plan_path = project / "task_plan.md"
        plan_text = plan_path.read_text(encoding="utf-8")
        plan_path.write_text(
            plan_text.replace("ACTIVE_LARGE", "ACTIVE_LARGE\n" + ("X" * 200_000)),
            encoding="utf-8",
        )
        self.bind("large-session", project)
        with mock.patch.dict(os.environ, {"PWF_HERMES_MAX_CONTEXT_BYTES": "8192"}, clear=False):
            payload = hooks.pre_llm_call(
                user_message="continue",
                session_id="large-session",
                platform="discord",
            )
        assert payload is not None
        size = len(payload["context"].encode("utf-8"))
        self.assertLess(size, 10_000)
        self.assertIn("CONTEXT TRUNCATED", payload["context"])

    def test_binding_survives_fresh_python_process(self) -> None:
        project = self.make_project("process-restart", "PROCESS_RESTART")
        self.bind("process-session", project)
        code = (
            "import importlib.util, pathlib, sys; "
            "root=pathlib.Path(sys.argv[1]); "
            "spec=importlib.util.spec_from_file_location('restart_plugin', root/'__init__.py', "
            "submodule_search_locations=[str(root)]); "
            "m=importlib.util.module_from_spec(spec); sys.modules['restart_plugin']=m; "
            "spec.loader.exec_module(m); "
            "from restart_plugin.project_bindings import resolve_bound_project; "
            "p=resolve_bound_project('process-session'); print(p or '')"
        )
        import subprocess
        result = subprocess.run(
            [sys.executable, "-c", code, str(PLUGIN_ROOT)],
            env=os.environ.copy(),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(str(project.resolve()), result.stdout.strip())

    def test_rebinding_clears_pending_reminder_from_previous_project(self) -> None:
        project_a = self.make_project("reminder-a", "REMINDER_A")
        project_b = self.make_project("reminder-b", "REMINDER_B")
        self.bind("reminder-session", project_a)
        hooks.post_tool_call(
            tool_name="write_file",
            session_id="reminder-session",
            args={"path": str(project_a / "file.py"), "content": "x"},
        )
        self.bind("reminder-session", project_b)
        payload = hooks.pre_llm_call(
            user_message="continue",
            session_id="reminder-session",
            platform="discord",
        )
        assert payload is not None
        self.assertNotIn("Update progress.md", payload["context"])
        self.assertIn("REMINDER_B", payload["context"])

    def test_unbind_storage_error_is_not_reported_as_success(self) -> None:
        with mock.patch.object(tools, "unbind_project", side_effect=bindings.BindingStoreError("storage unavailable")):
            result = json.loads(tools.planning_with_files_unbind_project(session_id="session-a"))
        self.assertFalse(result["ok"])
        self.assertFalse(result["unbound"])

    def test_scoped_plan_status_init_and_completion_use_same_active_plan(self) -> None:
        project = self.workspace / "scoped-tools"
        plan = project / ".planning" / "2026-01-01-feature"
        plan.mkdir(parents=True)
        plan.joinpath("task_plan.md").write_text(
            "# Scoped Plan\n\n## Current Phase\n\nScoped Phase\n\n## Phases\n\n"
            "### Phase 1: Scoped work\n**Status:** complete\n",
            encoding="utf-8",
        )
        project.joinpath(".planning", ".active_plan").write_text("2026-01-01-feature\n", encoding="utf-8")
        self.bind("scoped-tools-session", project)

        status = json.loads(tools.planning_with_files_status(session_id="scoped-tools-session"))
        initialized = json.loads(tools.planning_with_files_init(session_id="scoped-tools-session"))
        completion = json.loads(tools.planning_with_files_check_complete(session_id="scoped-tools-session"))

        self.assertTrue(status["exists"])
        self.assertEqual(str(plan.resolve()), status["plan_dir"])
        self.assertEqual(str(plan.resolve()), initialized["plan_dir"])
        self.assertFalse(project.joinpath("task_plan.md").exists())
        self.assertTrue(completion["complete"])

    def test_real_cli_post_hook_kwargs_preserve_cwd_reminder(self) -> None:
        project = self.make_project("cli-real", "CLI_REAL")
        old_cwd = Path.cwd()
        try:
            os.chdir(project)
            hooks.post_tool_call(
                tool_name="write_file",
                session_id="cli-real-session",
                task_id="cli-real-session",
                args={"path": "file.py", "content": "x"},
            )
            payload = hooks.pre_llm_call(
                user_message="continue",
                session_id="cli-real-session",
                platform="cli",
            )
        finally:
            os.chdir(old_cwd)
        assert payload is not None
        self.assertIn("Update progress.md", payload["context"])
        self.assertIn("CLI_REAL", payload["context"])

    def test_unbound_gateway_discards_cwd_reminder(self) -> None:
        project = self.make_project("gateway-post", "GATEWAY_POST")
        old_cwd = Path.cwd()
        try:
            os.chdir(project)
            hooks.post_tool_call(
                tool_name="write_file",
                session_id="gateway-post-session",
                task_id="gateway-post-session",
                args={"path": "file.py", "content": "x"},
            )
            payload = hooks.pre_llm_call(
                user_message="continue",
                session_id="gateway-post-session",
                platform="discord",
            )
        finally:
            os.chdir(old_cwd)
        self.assertIsNone(payload)

    def test_truncation_closes_nonce_plan_delimiter(self) -> None:
        import io
        payload = (
            b"===BEGIN-PLAN-DATA-ABC123===\n"
            + (b"X" * 10_000)
            + b"\n===END-PLAN-DATA-ABC123===\n"
        )
        context = hooks._bounded_context(io.BytesIO(payload), 4096)
        self.assertIn("===BEGIN-PLAN-DATA-ABC123===", context)
        self.assertIn("===END-PLAN-DATA-ABC123===", context)
        self.assertIn("CONTEXT TRUNCATED", context)

    def test_profile_roots_file_allows_gateway_projects_without_environment_config(self) -> None:
        roots_file = self.state_dir / "project-roots"
        roots_file.parent.mkdir(parents=True, exist_ok=True)
        roots_file.write_text("# One project root per line\n" + str(self.workspace) + "\n", encoding="utf-8")
        project = self.make_project("roots-file", "ROOTS_FILE")
        with mock.patch.dict(os.environ, {"PWF_HERMES_PROJECT_ROOTS": ""}, clear=False):
            bindings.reset_store_cache()
            result = self.bind("roots-file-session", project)
            resolved = bindings.resolve_bound_project("roots-file-session")
        self.assertTrue(result["ok"])
        self.assertEqual(project.resolve(), resolved)

    def test_task_id_fallback_can_bind_project(self) -> None:
        project = self.make_project("task-id", "TASK_ID")
        ctx = FakeContext()
        plugin.register(ctx)
        result = json.loads(
            ctx.tools["planning_with_files_bind_project"](
                {"cwd": str(project)},
                task_id="task-id-session",
            )
        )
        self.assertTrue(result["ok"])
        self.assertEqual(project.resolve(), bindings.resolve_bound_project("task-id-session"))


if __name__ == "__main__":
    unittest.main()
