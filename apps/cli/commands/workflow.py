from __future__ import annotations

import argparse
import asyncio
import json
import sys

from apps.cli.formatters import nonneg_float
from apps.cli.runtime import build_device_manager, build_workflows, default_database_path, open_store
from fluke_app import SessionRecorder, WorkflowRunner, new_session
from fluke_core.models.reading import Reading


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("workflow", help="List and run guided measurement workflows")
    workflow_subparsers = parser.add_subparsers(dest="workflow_command", required=True)

    list_parser = workflow_subparsers.add_parser("list", help="List available workflows")
    list_parser.set_defaults(func=handle_list)

    run_parser = workflow_subparsers.add_parser("run", help="Run a workflow interactively")
    run_parser.add_argument("--workflow", required=True, help="Workflow id to run")
    run_parser.add_argument("--device", required=True, help="BLE device identifier from scan output")
    run_parser.add_argument("--profile", default="fluke_376fc", help="Device profile id to use")
    run_parser.add_argument("--database", default=default_database_path(), help="SQLite database path (default: platform data dir)")
    run_parser.add_argument("--timeout", type=nonneg_float, default=0.0, help="Max seconds to wait for each step reading; 0 waits forever")
    run_parser.set_defaults(func=handle_run)


async def handle_list(args: argparse.Namespace) -> int:
    catalog = build_workflows()
    workflows = catalog.list()

    if not workflows:
        if getattr(args, "json", False):
            print("[]")
        else:
            print("No workflows available.")
        return 0

    if getattr(args, "json", False):
        items = []
        for wf in workflows:
            items.append({
                "workflow_id": wf.workflow_id,
                "title": wf.title,
                "category": wf.category,
                "description": wf.description,
                "step_count": len(wf.steps),
                "tags": list(wf.tags),
                "estimated_duration_min": wf.estimated_duration_min,
            })
        print(json.dumps(items, indent=2))
    else:
        print("Available workflows:")
        for wf in workflows:
            duration = f" (~{wf.estimated_duration_min} min)" if wf.estimated_duration_min else ""
            print(f"- {wf.title} [{wf.workflow_id}]")
            print(f"  category={wf.category} | steps={len(wf.steps)}{duration}")
            if wf.description:
                print(f"  {wf.description}")
    return 0


async def handle_run(args: argparse.Namespace) -> int:
    catalog = build_workflows()
    definition = catalog.get(args.workflow)
    if definition is None:
        print(f"Unknown workflow: {args.workflow}", file=sys.stderr)
        return 1

    db_path = args.database
    manager = build_device_manager()
    store = open_store(db_path)
    recorder = SessionRecorder(store.sessions, store.readings, store.markers)
    runner = WorkflowRunner(catalog, store.workflow_runs, store.workflow_step_results)

    latest_reading: Reading | None = None

    def on_reading(reading: Reading) -> None:
        nonlocal latest_reading
        latest_reading = reading
        recorder.on_reading(reading)

    manager.subscribe_readings(on_reading)

    try:
        print(f"Connecting to {args.device}...", file=sys.stderr)
        device = await manager.connect(args.device, profile_id=args.profile)
        store.upsert_device(device)

        session = recorder.start(
            new_session(
                device_id=device.device_id,
                title=f"Workflow: {definition.title}",
                app_version="0.1.0",
                profile_id=device.profile_id or args.profile,
            )
        )

        await manager.start_stream()

        print(f"\n{'=' * 60}")
        print(f"  WORKFLOW: {definition.title}")
        print(f"  {definition.description}")
        print(f"  Steps: {len(definition.steps)}")
        print(f"{'=' * 60}\n")

        state = runner.start(args.workflow, session.session_id)

        for i, step in enumerate(definition.steps):
            print(f"--- Step {i + 1}/{len(definition.steps)}: {step.title} ---")
            print(f"  {step.instruction}")
            if step.expected_measurement_type:
                print(f"  Expected: {step.expected_measurement_type.value}", end="")
                if step.expected_unit:
                    print(f" ({step.expected_unit})", end="")
                print()
            if step.note_prompt:
                print(f"  Note prompt: {step.note_prompt}")

            print()

            if step.capture:
                # Wait for a valid reading
                print("  Waiting for reading... (press Enter to capture, 's' to skip)")
                action = await _prompt_step_action()

                if action == "skip":
                    note = None
                    if step.note_prompt:
                        note = await _prompt_text(f"  Note ({step.note_prompt}): ")
                    state = runner.skip_current_step(note=note)
                    print(f"  >> SKIPPED\n")
                else:
                    if latest_reading is None:
                        print("  No reading available yet. Waiting...", file=sys.stderr)
                        await asyncio.sleep(2.0)
                    note = None
                    if step.note_prompt:
                        note = await _prompt_text(f"  Note ({step.note_prompt}): ")
                    try:
                        state = runner.complete_current_step(latest_reading=latest_reading, note=note)
                        if latest_reading:
                            print(f"  >> CAPTURED: {latest_reading.display_text} ({latest_reading.value} {latest_reading.unit})")
                        else:
                            print(f"  >> CAPTURED (no reading)")
                    except RuntimeError as exc:
                        print(f"  >> ERROR: {exc}", file=sys.stderr)
                        print("  Skipping step due to error.")
                        state = runner.skip_current_step(note=f"Auto-skipped: {exc}")
            else:
                print("  Press Enter to complete, 's' to skip.")
                action = await _prompt_step_action()
                note = None
                if step.note_prompt:
                    note = await _prompt_text(f"  Note ({step.note_prompt}): ")
                if action == "skip":
                    state = runner.skip_current_step(note=note)
                    print(f"  >> SKIPPED\n")
                else:
                    state = runner.complete_current_step(note=note)
                    print(f"  >> COMPLETED\n")

        print(f"{'=' * 60}")
        print(f"  WORKFLOW COMPLETE: {state.run.result.value}")
        print(f"  Session: {session.session_id}")
        print(f"  Readings: {recorder.reading_count()}")
        print(f"{'=' * 60}")

    finally:
        recorder.stop()
        await manager.disconnect()
        store.close()

    return 0


async def _prompt_step_action() -> str:
    """Read user input: Enter to complete/capture, 's' to skip."""
    loop = asyncio.get_event_loop()
    line = await loop.run_in_executor(None, sys.stdin.readline)
    return "skip" if line.strip().lower() == "s" else "complete"


async def _prompt_text(prompt: str) -> str | None:
    """Read optional text input from user."""
    loop = asyncio.get_event_loop()
    print(prompt, end="", flush=True)
    line = await loop.run_in_executor(None, sys.stdin.readline)
    text = line.strip()
    return text if text else None
