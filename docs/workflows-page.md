# Workflows Page Guide

The desktop app's `Workflows` page is the guided procedure area of the GUI. It lets an operator:

- browse available workflow definitions
- inspect the steps in a workflow before starting it
- start a guided run tied to an active or auto-created session
- complete, skip, or cancel workflow steps
- review recent workflow runs
- export a workflow report as Markdown
- create new workflow definitions directly from the GUI

This page is backed by the shared workflow catalog and workflow runner used by the rest of the app. A workflow is data-defined, so once a valid workflow JSON file exists in the workflow catalog, the desktop UI can display and run it without additional code changes.

## Page Layout

The `Workflows` tab is split into two main columns.

### Left Column

- `Available Workflows`: list of workflow definitions currently loaded into the catalog
- `Start Workflow`: starts the selected workflow
- `New Workflow`: opens the workflow builder dialog for creating a new workflow definition

Each workflow row shows:

- workflow title
- category
- number of steps

### Right Column

The right side shows the currently selected workflow or workflow run.

- status text
- workflow title
- description
- progress
- current step
- current instruction
- current requirement
- active session
- latest capture summary
- run result
- selected run summary
- optional note input for the current step

Below the summary area are:

- `Completed Steps`: table of steps already completed or skipped in the active or selected run
- `Recent Workflow Runs`: recent execution history across workflows
- `Workflow Report`: generated report text for the selected definition or run

Action buttons:

- `Complete Step`
- `Skip Step`
- `Cancel Workflow`
- `Export Workflow Report`

## How Workflow Runs Behave

The workflow page supports two modes:

- definition review mode
- workflow run mode

### Definition Review Mode

When you click a workflow in `Available Workflows`, the page shows:

- the workflow metadata
- the next steps to be performed
- a definition-only report preview

This mode is useful for reviewing instructions before starting.

### Workflow Run Mode

When you start a workflow, the app:

1. Resolves the selected workflow definition.
2. Uses the active logging session if one already exists.
3. Creates a new logging session automatically if no session is active.
4. Starts a workflow run tied to that session.
5. Updates the page to show live progress.

For each step:

- `Complete Step` marks the current step complete
- if the step is a capture step, the app records the latest live meter reading
- `Skip Step` records the step as skipped
- the optional note field is attached to the step result when completing or skipping

When the workflow finishes:

- the run is marked completed
- the report updates with all results
- if the workflow created the session automatically, the app can stop that session when the workflow completes

If a workflow is canceled:

- the run is marked aborted
- the status text updates accordingly
- if the workflow owned the session, the session is stopped

## Using the Workflows Page

### Review a Workflow

1. Open the `Workflows` tab.
2. Click a workflow in `Available Workflows`.
3. Read the description, instructions, and requirement text.
4. Check the report preview and completed step table if you are viewing a prior run.

### Start a Workflow

1. Select a workflow in the left-hand list.
2. Click `Start Workflow`.
3. Follow the instruction shown in the `Current Step` and `Instruction` sections.

### Complete a Step

1. Perform the action described in the current instruction.
2. If needed, enter a note in `Optional step note`.
3. Click `Complete Step`.

For capture steps, make sure the meter is connected and a current live reading is available before you complete the step.

### Skip a Step

1. Enter an optional reason in the note box if useful.
2. Click `Skip Step`.

### Cancel a Workflow

1. Click `Cancel Workflow`.
2. Confirm the cancellation when prompted.

### Review Prior Runs

1. Select a row in `Recent Workflow Runs`.
2. The page refreshes to show the selected historical run.
3. Review step outcomes and report text.

### Export a Workflow Report

1. Select a historical workflow run, or complete a workflow run.
2. Click `Export Workflow Report`.
3. The app writes a Markdown report into the configured export directory.

## Creating a New Workflow in the GUI

The `New Workflow` button opens a workflow builder dialog.

### Workflow-Level Fields

- `Workflow ID`: unique identifier used in JSON and persistence
- `Title`: user-facing name
- `Description`: longer explanation of what the workflow is for
- `Category`: grouping label shown in the workflow list
- `Tags`: comma-separated tags
- `Estimated Duration`: optional duration in minutes

### Step List

The left side of the dialog is the ordered step list.

Available controls:

- `Add Step`
- `Remove Step`
- `Move Up`
- `Move Down`

The order of steps in the list is the execution order of the workflow.

### Step Detail Fields

Each step supports:

- `Title`: user-facing step name
- `Instruction`: what the operator should do
- `This step captures a meter reading`: checkbox that makes the step a capture step
- `Measurement Type`: expected reading type for capture steps
- `Expected Unit`: optional expected unit for capture steps
- `Note Prompt`: optional prompt text to guide note entry

Important behavior:

- `Measurement Type` and `Expected Unit` are intentionally disabled until `This step captures a meter reading` is checked
- this is by design, because non-capture steps are manual checklist steps and do not require a live reading

### Save Behavior

When you click `Create Workflow`, the app:

1. Validates the workflow data.
2. Builds a `WorkflowDefinition`.
3. Writes a JSON file into the default workflow directory.
4. Reloads the workflow catalog used by the desktop app.
5. Selects the new workflow in the page.

If saving fails, the app shows a `Workflow Save Failed` dialog with the error text.

## Recommended Workflow Authoring Pattern

For a solid operator experience:

- use a short, specific title
- keep each instruction action-oriented
- use capture steps only when a meter reading is actually required
- use manual steps for safety checks, setup, and interpretation
- use note prompts for steps where a technician may need to record context
- keep the category broad and the title specific

Examples:

- category `Battery`
- title `Battery Pack Check Validation`

- category `Solar`
- title `Solar Panel Test`

## Workflow JSON Format

The GUI builder writes the same workflow schema used by existing built-in workflow files.

Example:

```json
{
  "workflow_id": "battery_pack_check_v1",
  "title": "Battery Pack Check",
  "description": "Validate battery pack voltage across a guided checklist.",
  "category": "Battery",
  "estimated_duration_min": 5,
  "tags": [
    "battery",
    "voltage"
  ],
  "steps": [
    {
      "id": "verify_pack_isolated",
      "title": "Verify Pack Is Isolated",
      "instruction": "Confirm the pack is safe to measure and isolated as needed.",
      "capture": false,
      "note_prompt": "Record any safety notes."
    },
    {
      "id": "measure_pack_voltage",
      "title": "Measure Pack Voltage",
      "instruction": "Measure the battery pack voltage in DC voltage mode.",
      "capture": true,
      "expected_measurement_type": "voltage_dc",
      "expected_unit": "V"
    }
  ]
}
```

## Creating New Workflows Manually

You can also create workflows without the GUI by adding a JSON file directly to [workflows](C:/Users/zachv/python/fluke-app/workflows).

Rules to follow:

- file name should usually match `workflow_id`, for example `battery_pack_check_v1.json`
- `workflow_id` must be unique
- every step needs a unique `id`
- every step should have a `title` and `instruction`
- set `capture` to `true` only when the step should record a live reading
- `expected_measurement_type` should match a valid measurement enum value such as `voltage_dc`, `current_ac`, or `resistance`

After adding a file manually:

- restart the desktop app, or
- trigger a catalog reload path in code if you are developing against the runtime

## Plugin-Contributed Workflows

The desktop app can also load workflows from plugin directories in addition to the built-in [workflows](C:/Users/zachv/python/fluke-app/workflows) folder.

That means the visible workflow list may contain:

- built-in workflows
- plugin-provided workflows
- workflows created through the GUI and saved into the default workflow directory

The workflows page does not need special-case UI for plugin workflows. If a valid workflow definition is present in the catalog, it will appear in the page automatically.

## Troubleshooting

### A New Workflow Does Not Appear

Check the following:

- the workflow save succeeded without an error dialog
- the workflow ID is unique
- the JSON file exists in [workflows](C:/Users/zachv/python/fluke-app/workflows)
- the JSON is valid
- the app was able to reload the workflow catalog

### A Capture Step Cannot Be Completed

Common causes:

- the meter is not connected
- no current live reading is available
- the workflow expects a capture step but the operator has not produced a reading yet

### The Measurement Type and Unit Fields Are Disabled

This is expected until `This step captures a meter reading` is checked for that step.

## Relevant Code

Primary desktop workflow GUI code:

- [views.py](C:/Users/zachv/python/fluke-app/apps/desktop/views.py)
- [presenters.py](C:/Users/zachv/python/fluke-app/apps/desktop/presenters.py)

Shared workflow runtime and catalog code:

- [workflow_catalog.py](C:/Users/zachv/python/fluke-app/packages/fluke_app/workflow_catalog.py)
- [workflow_runner.py](C:/Users/zachv/python/fluke-app/packages/fluke_app/workflow_runner.py)
- [workflow.py](C:/Users/zachv/python/fluke-app/packages/fluke_core/models/workflow.py)
