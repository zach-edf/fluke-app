# Desktop UI Architecture

This guide explains how the desktop application is structured internally so contributors can make GUI changes without fighting the architecture.

## High-Level Structure

The desktop app lives under:

- [apps/desktop](../../apps/desktop)

The major pieces are:

- runtime construction
- presenter state and behavior
- immutable viewmodels
- Qt widget layout and refresh
- theme and chart widgets

## Main Files

Primary desktop files:

- [runtime.py](../../apps/desktop/runtime.py)
- [presenters.py](../../apps/desktop/presenters.py)
- [viewmodels.py](../../apps/desktop/viewmodels.py)
- [views.py](../../apps/desktop/views.py)
- [theme.py](../../apps/desktop/theme.py)
- [widgets/chart_widget.py](../../apps/desktop/widgets/chart_widget.py)
- [\_qt.py](../../apps/desktop/_qt.py)

## Runtime Construction

`runtime.py` builds the shared desktop runtime.

Responsibilities:

- create the BLE adapter
- open the SQLite store
- build the profile registry
- load plugin bundle information
- build the workflow catalog
- create the `AppPresenter`
- provide an async runner for GUI-triggered async work

The runtime object exposes:

- `presenter`
- `runner`
- `store`
- `submit()` for async tasks

## Presenter Role

`AppPresenter` in [presenters.py](../../apps/desktop/presenters.py) is the main behavioral layer for the desktop app.

Responsibilities:

- orchestrate device connection and disconnect flows
- own current desktop state
- transform domain/store data into viewmodels
- react to live readings
- control session recording
- control workflow execution
- coordinate export behavior
- coordinate alert thresholds and reconnect behavior

The presenter deliberately sits between raw services and Qt widgets so the view layer can stay comparatively thin.

## Viewmodel Pattern

`viewmodels.py` defines immutable dataclasses for each desktop surface.

Examples:

- `HomeViewModel`
- `DiscoveryViewModel`
- `LiveReadingViewModel`
- `SessionViewModel`
- `SettingsViewModel`
- `WorkflowViewModel`

Pattern:

- presenter mutates its internal state by replacing dataclass instances
- views read those snapshots and render them
- this keeps the Qt layer simpler and reduces hidden widget state

## View Layer

`views.py` owns widget construction and refresh logic.

The pattern is:

1. build a panel with Qt widgets
2. store widget refs in a `_PanelRefs` object
3. wire user actions to presenter calls
4. periodically refresh widget state from presenter viewmodels

### Panel builders

Each tab is created by a dedicated builder function such as:

- `_home_panel()`
- `_discovery_panel()`
- `_live_panel()`
- `_session_panel()`
- `_workflow_panel()`
- `_settings_panel()`

### Refresh functions

Each tab has a matching refresh function such as:

- `_refresh_home()`
- `_refresh_discovery()`
- `_refresh_live()`
- `_refresh_session()`
- `_refresh_workflow()`
- `_refresh_settings()`

The main window starts a timer and refreshes all tabs on a short interval.

That means contributor changes should usually follow this pattern:

- panel builder defines widgets and signal wiring
- presenter owns business state
- refresh function pushes presenter state into widgets

## Threading and Async Model

The desktop app mixes Qt and async BLE behavior.

Key idea:

- async operations are submitted through the runtime runner
- synchronous button actions that only touch presenter state can call presenter methods directly
- connection, scan, and disconnect tasks use `_submit(...)`
- synchronous presenter operations use `_safe_call(...)`

This separation is important. If a GUI action awaits BLE or transport behavior, it should generally go through the runner instead of blocking the UI thread.

## Main Window Behavior

The main window:

- creates all tabs at startup
- installs keyboard shortcuts
- starts a periodic refresh timer
- updates the status bar from the latest home/live viewmodels
- attempts disconnect/shutdown work during close

## Home Tab Internals

The home tab is a compact summary view.

It mainly reflects presenter state:

- connection text and health
- active device text
- active session text
- recent device list
- top-level message text

It is not the source of connection behavior. The presenter owns that.

## Discovery Tab Internals

The discovery tab:

- triggers scans
- reflects scan results
- stores the selected device id
- triggers connect on the selected device

The table selection only updates the presenter's selected device id. The actual BLE connect path lives in the presenter and shared app services.

## Live Tab Internals

The live tab is where most real-time behavior is visible.

Key contributor details:

- the live chart is driven by the presenter's in-memory reading buffer and derived chart modes
- measurement-context changes create a new derived boundary for the live chart
- alert thresholds are configured from the view but evaluated in the presenter
- session creation happens from presenter `start_logging(...)`
- markers are recorded via the shared recorder

Important presenter-owned behaviors:

- stale reading detection
- reconnect state
- alert trigger state
- live chart mode and context-change notices
- session summary text

## Session Tab Internals

The session tab is a replay surface, not a raw live recorder.

Key contributor details:

- session replay is derived from stored readings
- measurement view filtering is computed in the presenter
- comparison overlays are computed in the presenter
- the view mostly renders selected tables, labels, and chart data

If you need to change replay grouping behavior, the change likely belongs in the presenter helper logic, not directly in the view.

## Workflows Tab Internals

The workflows tab is a presenter-driven wrapper around the shared `WorkflowRunner`.

Key responsibilities:

- list available workflow definitions
- select definitions and recent runs
- start workflow runs
- complete/continue/retake/skip/cancel steps
- surface capture state and staged readings
- render historical run details
- export workflow reports
- launch the workflow builder dialog

Workflow authoring from the GUI is currently implemented in [views.py](../../apps/desktop/views.py) and save/reload behavior is handled in [presenters.py](../../apps/desktop/presenters.py).

For end-user workflow behavior, see [Workflows Page Guide](../workflows-page.md).

## Settings Tab Internals

The settings tab currently provides:

- database path display
- diagnostics text
- export directory input
- live theme switching

Important note:

- theme and export directory changes are current-runtime settings, not a persisted settings subsystem

If you add settings persistence later, it should be designed deliberately rather than inferred from the current in-memory behavior.

## Theme System

`theme.py` contains the QSS themes and chart-related color registry.

Current themes:

- light
- dark
- fluke

The theme system also drives chart coloring through tokens consumed by the chart widget.

If you add new widget types to the desktop UI, update theme coverage so the new controls look intentional across all themes.

## Chart Widget

The chart widget wrapper in [chart_widget.py](../../apps/desktop/widgets/chart_widget.py) encapsulates:

- live and replay chart setup
- placeholder state
- marker points
- comparison series
- theme application
- PNG export

If a behavior is specific to chart rendering, axis setup, or export, change it there instead of scattering chart-specific logic through `views.py`.

## Qt Import Boundary

The desktop app centralizes PySide6 imports through [\_qt.py](../../apps/desktop/_qt.py).

Reasons:

- clearer failure mode if PySide6 is missing
- fewer direct import paths to maintain
- simpler type-checking and IDE behavior

If you add a new Qt widget to the desktop app, add it to `_qt.py` instead of importing PySide6 directly elsewhere.

## Common Change Patterns

### Add a new visible field to a tab

Typical path:

1. add state to the relevant viewmodel if needed
2. populate it in the presenter
3. add the widget in the panel builder
4. bind it in the refresh function
5. add tests

### Add a new button

Typical path:

1. create the widget in the relevant panel builder
2. connect it to `_submit(...)` or `_safe_call(...)`
3. implement or call presenter behavior
4. update enable/disable state in the refresh function

### Add a new dialog

Typical path:

1. define the dialog in `views.py` if it is tightly desktop-specific
2. keep validation in the dialog or presenter as appropriate
3. keep persistence and domain behavior in the presenter/shared layers

### Change workflow or session behavior

Before editing widgets, check whether the logic should really change in:

- presenter helpers
- workflow runner
- export service
- store layer

## Testing Targets For Desktop Work

Relevant tests:

- [test_desktop_presenter.py](../../tests/unit/test_desktop_presenter.py)
- [test_desktop_views.py](../../tests/unit/test_desktop_views.py)
- [test_desktop_chart_widget.py](../../tests/unit/test_desktop_chart_widget.py)

Run them with:

```powershell
python -m unittest tests.unit.test_desktop_presenter tests.unit.test_desktop_views tests.unit.test_desktop_chart_widget
```

## Related Guides

- [Development Workflow](development-workflow.md)
- [Testing Guide](testing-guide.md)
- [Architecture Overview](../architecture.md)
- [Desktop User Guide](../desktop-guide.md)
