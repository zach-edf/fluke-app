from __future__ import annotations

import argparse
import asyncio
import json
import sys

from apps.cli.formatters import nonneg_float
from apps.cli.runtime import attach_connection_diagnostics, build_device_manager, build_workflows, default_database_path, open_store
from fluke_app import ReportService, SessionRecorder, WorkflowRunner, new_session
from fluke_core.enums import WorkflowVerdict
from fluke_core.models.reading import Reading

_VERDICT_LABELS = {
    WorkflowVerdict.PASS: "PASS",
    WorkflowVerdict.FAIL: "FAIL",
    WorkflowVerdict.NOT_EVALUATED: "n/a",
}


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("workflow", help="List and run guided measurement workflows")
    workflow_subparsers = parser.add_subparsers(dest="workflow_command", required=True)

    list_parser = workflow_subparsers.add_parser("list", help="List available workflows")
    list_parser.set_defaults(func=handle_list)

    run_parser = workflow_subparsers.add_parser("run", help="Run a workflow interactively")
    run_parser.add_argument("--workflow", required=True, help="Workflow id to run")
    run_parser.add_argument("--device", required=True, help="BLE device identifier from scan output")
    run_parser.add_argument("--profile", default="fluke_376fc", help="Device profile id to use")
    run_parser.add_argument("--database", default=None, help="SQLite database path (default: platform data dir)")
    run_parser.add_argument("--timeout", type=nonneg_float, default=0.0, help="Max seconds to wait for each step reading; 0 waits forever")
    run_parser.set_defaults(func=handle_run)

    history_parser = workflow_subparsers.add_parser("history", help="Show recent workflow runs and verdicts")
    history_parser.add_argument("--database", default=None, help="SQLite database path (default: platform data dir)")
    history_parser.add_argument("--limit", type=int, default=10, help="Number of recent runs to show")
    history_parser.add_argument("--run", default=None, help="Show step results for a specific run id")
    history_parser.set_defaults(func=handle_history)

    report_parser = workflow_subparsers.add_parser("report", help="Render a workflow run to a PDF job report")
    report_parser.add_argument("--run", required=True, help="Workflow run id to render")
    report_parser.add_argument("--output", required=True, help="Output PDF path")
    report_parser.add_argument("--database", default=None, help="SQLite database path (default: platform data dir)")
    report_parser.add_argument("--business-name", default=None, help="Business name shown in the report header")
    report_parser.add_argument("--logo", default=None, help="Path to a logo image for the report header")
    report_parser.add_argument("--customer", default=None, help="Customer name")
    report_parser.add_argument("--site", default=None, help="Site / location")
    report_parser.add_argument("--job", default=None, help="Job or work-order number")
    report_parser.add_argument("--technician", default=None, help="Technician name")
    report_parser.add_argument("--report-notes", default=None, help="Free-form notes for the report")
    report_parser.set_defaults(func=handle_report)

    customize_parser = workflow_subparsers.add_parser(
        "customize",
        help="Copy a workflow into your user folder so its steps and pass/fail limits can be edited",
    )
    customize_parser.add_argument("--workflow", required=True, help="Workflow id to copy")
    customize_parser.add_argument(
        "--force", action="store_true", help="Overwrite an existing customized copy"
    )
    customize_parser.set_defaults(func=handle_customize)


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


async def handle_customize(args: argparse.Namespace) -> int:
    from fluke_app import save_workflow_definition, user_workflow_directory

    catalog = build_workflows()
    definition = catalog.get(args.workflow)
    if definition is None:
        print(f"Unknown workflow {args.workflow!r}. Use `fluke workflow list` to see ids.", file=sys.stderr)
        return 1
    try:
        path = save_workflow_definition(definition, overwrite=args.force)
    except FileExistsError as exc:
        print(f"Customized copy already exists: {exc}", file=sys.stderr)
        print("Edit that file directly, or pass --force to overwrite it with the built-in defaults.", file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        print(json.dumps({"workflow_id": definition.workflow_id, "path": str(path)}, indent=2))
    else:
        print(f"Editable copy saved to: {path}")
        print("Edit the per-step \"acceptance\" limits in the JSON; your copy overrides the built-in workflow.")
        print(f"User workflow folder: {user_workflow_directory()}")
    return 0


async def handle_run(args: argparse.Namespace) -> int:
    catalog = build_workflows()
    definition = catalog.get(args.workflow)
    if definition is None:
        print(f"Unknown workflow: {args.workflow}", file=sys.stderr)
        return 1

    db_path = args.database or default_database_path()
    manager = build_device_manager()
    attach_connection_diagnostics(manager)
    store = open_store(db_path)
    recorder = SessionRecorder(store.sessions, store.readings, store.markers)
    runner = WorkflowRunner(catalog, store.workflow_runs, store.workflow_step_results)

    latest_reading: Reading | None = None
    finished = asyncio.Event()
    terminal_error: str | None = None

    def on_reading(reading: Reading) -> None:
        nonlocal latest_reading
        latest_reading = reading
        recorder.on_reading(reading)

    manager.subscribe_readings(on_reading)
    manager.subscribe_disconnects(lambda: _mark_workflow_disconnect(manager, finished, _set_terminal_error))

    def _set_terminal_error(message: str) -> None:
        nonlocal terminal_error
        terminal_error = message

    try:
        print(f"Connecting to {args.device}...", file=sys.stderr)
        device = await manager.establish_session(args.device, profile_id=args.profile)
        store.upsert_device(device)

        session = recorder.start(
            new_session(
                device_id=device.device_id,
                title=f"Workflow: {definition.title}",
                app_version="0.1.0",
                profile_id=device.profile_id or args.profile,
            )
        )

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
                if finished.is_set():
                    raise RuntimeError(f"Workflow stopped because recovery failed: {terminal_error or 'Device disconnected.'}")
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
                        _print_step_verdict(state)
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
        print(f"  Overall verdict: {_VERDICT_LABELS.get(state.run.verdict, 'n/a')}")
        print(f"  Session: {session.session_id}")
        print(f"  Run ID: {state.run.run_id}")
        print(f"  Readings: {recorder.reading_count()}")
        print(f"  Tip: fluke workflow report --run {state.run.run_id} --output report.pdf")
        print(f"{'=' * 60}")

    finally:
        recorder.stop()
        await manager.disconnect()
        store.close()

    if terminal_error:
        raise RuntimeError(f"Workflow stopped because recovery failed: {terminal_error}")
    return 0


def _print_step_verdict(state) -> None:
    if not state.completed_steps:
        return
    last = state.completed_steps[-1]
    if last.verdict == WorkflowVerdict.NOT_EVALUATED:
        return
    label = _VERDICT_LABELS.get(last.verdict, "n/a")
    print(f"  >> {label}: {last.verdict_detail or ''}".rstrip())


async def handle_history(args: argparse.Namespace) -> int:
    catalog = build_workflows()
    store = open_store(args.database or default_database_path())
    runner = WorkflowRunner(catalog, store.workflow_runs, store.workflow_step_results)
    use_json = getattr(args, "json", False)
    try:
        if args.run:
            run = store.workflow_runs.get(args.run)
            if run is None:
                print(f"Unknown workflow run: {args.run}", file=sys.stderr)
                return 1
            results = runner.results_for_run(args.run)
            if use_json:
                print(json.dumps(_run_detail_payload(run, results), indent=2))
                return 0
            print(f"Run {run.run_id} [{run.workflow_id}] - {run.result.value} - verdict {_VERDICT_LABELS.get(run.verdict, 'n/a')}")
            for res in results:
                label = _VERDICT_LABELS.get(res.verdict, "n/a")
                reading = res.reading.display_text if res.reading is not None else "-"
                print(f"  {res.step_index + 1}. {res.step_id}: {res.status.value} | reading {reading} | {label}")
                if res.verdict_detail:
                    print(f"       {res.verdict_detail}")
            return 0

        runs = runner.list_recent_runs(limit=args.limit)
        if use_json:
            print(json.dumps([_run_summary_payload(run) for run in runs], indent=2))
            return 0
        if not runs:
            print("No workflow runs recorded yet.")
            return 0
        print("Recent workflow runs:")
        for run in runs:
            started = run.started_at.strftime("%Y-%m-%d %H:%M:%S")
            print(f"- {run.run_id} [{run.workflow_id}]")
            print(f"    result={run.result.value} | verdict={_VERDICT_LABELS.get(run.verdict, 'n/a')} | started={started}")
        return 0
    finally:
        store.close()


def _run_summary_payload(run) -> dict:
    return {
        "run_id": run.run_id,
        "workflow_id": run.workflow_id,
        "session_id": run.session_id,
        "result": run.result.value,
        "verdict": run.verdict.value,
        "started_at": run.started_at.isoformat(),
        "ended_at": None if run.ended_at is None else run.ended_at.isoformat(),
    }


def _run_detail_payload(run, results) -> dict:
    payload = _run_summary_payload(run)
    payload["steps"] = [
        {
            "step_id": res.step_id,
            "step_index": res.step_index,
            "status": res.status.value,
            "verdict": res.verdict.value,
            "verdict_detail": res.verdict_detail,
            "reading": None if res.reading is None else res.reading.as_dict(),
            "note": res.note,
        }
        for res in results
    ]
    return payload


async def handle_report(args: argparse.Namespace) -> int:
    catalog = build_workflows()
    store = open_store(args.database or default_database_path())
    try:
        service = ReportService(
            catalog,
            store.workflow_runs,
            store.workflow_step_results,
            store.sessions,
            store.devices,
        )
        meta = {
            "business_name": args.business_name,
            "logo_path": args.logo,
            "customer_name": args.customer,
            "site": args.site,
            "job_number": args.job,
            "technician": args.technician,
            "notes": args.report_notes,
        }
        meta = {key: value for key, value in meta.items() if value}
        # Persist any supplied metadata with the run for future reports.
        if meta:
            WorkflowRunner(catalog, store.workflow_runs, store.workflow_step_results).set_report_meta(args.run, meta)
        try:
            output = service.render_workflow_report(args.run, args.output, meta_overrides=meta)
        except Exception as exc:  # noqa: BLE001 - surface a clean CLI error
            print(f"Could not render report: {exc}", file=sys.stderr)
            return 1
        if getattr(args, "json", False):
            print(json.dumps({"run_id": args.run, "output": output}))
        else:
            print(f"Wrote workflow report to {output}")
        return 0
    finally:
        store.close()


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


def _mark_workflow_disconnect(manager, finished: asyncio.Event, set_message) -> None:
    status = manager.latest_connection_diagnostics()
    set_message("" if status is None else (status.last_error_text or status.message))
    finished.set()
