from __future__ import annotations

from typing import Any

from .goal_budget import install_goal_budget_bridge
from .hooks import post_tool_call, pre_llm_call
from .tools import (
    planning_with_files_bind_project,
    planning_with_files_check_complete,
    planning_with_files_init,
    planning_with_files_start_auto,
    planning_with_files_status,
    planning_with_files_stop_auto,
    planning_with_files_unbind_project,
)


def _runtime_session(kwargs: dict[str, Any]) -> str:
    return str(kwargs.get("session_id") or kwargs.get("task_id") or "")


def _runtime_platform(kwargs: dict[str, Any]) -> str:
    return str(kwargs.get("platform") or "")


def register(ctx: Any) -> None:
    install_goal_budget_bridge()
    ctx.register_tool(
        name="planning_with_files_bind_project",
        toolset="terminal",
        schema={
            "name": "planning_with_files_bind_project",
            "description": "Bind the current Hermes session to a PWF project directory. Rebinding switches projects for this session only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cwd": {"type": "string", "description": "Existing project directory inside an allowed PWF project root."},
                },
                "required": ["cwd"],
            },
        },
        handler=lambda args, **kw: planning_with_files_bind_project(
            cwd=args.get("cwd", ""),
            session_id=_runtime_session(kw),
        ),
        description="Bind this Hermes session to a planning-with-files project.",
    )
    ctx.register_tool(
        name="planning_with_files_unbind_project",
        toolset="terminal",
        schema={
            "name": "planning_with_files_unbind_project",
            "description": "Remove the PWF project binding for the current Hermes session.",
            "parameters": {"type": "object", "properties": {}},
        },
        handler=lambda args, **kw: planning_with_files_unbind_project(
            session_id=_runtime_session(kw),
        ),
        description="Unbind this Hermes session from its planning-with-files project.",
    )
    ctx.register_tool(
        name="planning_with_files_init",
        toolset="terminal",
        schema={
            "name": "planning_with_files_init",
            "description": "Create planning-with-files markdown files in the bound or explicitly selected project directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "template": {"type": "string", "description": "Template name, e.g. default or analytics."},
                    "cwd": {"type": "string", "description": "Target project directory. Defaults to this session's bound project."},
                },
            },
        },
        handler=lambda args, **kw: planning_with_files_init(
            template=args.get("template", "default"),
            cwd=args.get("cwd", ""),
            session_id=_runtime_session(kw),
            platform=_runtime_platform(kw),
        ),
        description="Initialize planning-with-files state files.",
    )
    ctx.register_tool(
        name="planning_with_files_status",
        toolset="terminal",
        schema={
            "name": "planning_with_files_status",
            "description": "Summarize planning state for the bound or explicitly selected project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cwd": {"type": "string", "description": "Target project directory. Defaults to this session's bound project."},
                },
            },
        },
        handler=lambda args, **kw: planning_with_files_status(
            cwd=args.get("cwd", ""),
            session_id=_runtime_session(kw),
            platform=_runtime_platform(kw),
        ),
        description="Show planning-with-files status summary.",
    )
    ctx.register_tool(
        name="planning_with_files_start_auto",
        toolset="terminal",
        schema={
            "name": "planning_with_files_start_auto",
            "description": "Arm the bound PWF plan and activate a Hermes standing goal for its current phase.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_turns": {
                        "type": "integer",
                        "description": "Optional goal turn budget. Defaults to Hermes goals.max_turns.",
                        "minimum": 1,
                        "maximum": 1000,
                    },
                },
            },
        },
        handler=lambda args, **kw: planning_with_files_start_auto(
            session_id=_runtime_session(kw),
            platform=_runtime_platform(kw),
            max_turns=args.get("max_turns", 0),
        ),
        description="Start autonomous execution of the bound PWF plan's active phase.",
    )
    ctx.register_tool(
        name="planning_with_files_stop_auto",
        toolset="terminal",
        schema={
            "name": "planning_with_files_stop_auto",
            "description": "Disarm PWF autonomous mode and mark the current Hermes standing goal done.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Verified completion reason stored with the goal.",
                    },
                },
            },
        },
        handler=lambda args, **kw: planning_with_files_stop_auto(
            session_id=_runtime_session(kw),
            platform=_runtime_platform(kw),
            reason=args.get("reason", "PWF phase completed and verified"),
        ),
        description="Stop autonomous PWF phase execution cleanly.",
    )
    ctx.register_tool(
        name="planning_with_files_check_complete",
        toolset="terminal",
        schema={
            "name": "planning_with_files_check_complete",
            "description": "Run the completion check for the bound or explicitly selected project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cwd": {"type": "string", "description": "Target project directory. Defaults to this session's bound project."},
                },
            },
        },
        handler=lambda args, **kw: planning_with_files_check_complete(
            cwd=args.get("cwd", ""),
            session_id=_runtime_session(kw),
            platform=_runtime_platform(kw),
        ),
        description="Check whether all planning phases are complete.",
    )
    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("post_tool_call", post_tool_call)
