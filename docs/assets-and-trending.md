# Assets and Trending

Assets let maintenance techs attach measurement sessions to a specific piece of
equipment and trend its readings over time - for example, "this motor's inrush
was 42 A in January and 51 A today."

The feature is optional and unobtrusive: if you never create an asset, nothing
about the existing capture, session, or export behavior changes. Old sessions
recorded before this feature remain unassigned.

## Concepts

### Asset

An asset is a tracked piece of equipment:

- `name` - human label (e.g. "Line 3 Drive Motor")
- `asset_type` - free text, with suggested categories: `motor`, `panel`,
  `HVAC unit`, `battery`, `charger`, `transformer`, `generator`, `pump`, `other`
- `location` - where it lives (e.g. "Bay 2, Panel A")
- `notes` - free-form notes
- `created_at` - set automatically

### Session linkage

Any recorded session can carry an optional `asset_id`. Sessions can be linked:

- when you start logging (Live Reading tab, or `fluke log --asset`)
- retroactively (Session tab, or `fluke sessions assign-asset`)

Deleting an asset never deletes sessions - linked sessions simply become
unassigned again.

## Trend model

For a given asset, the trend service aggregates every linked session into a time
series per measurement type. For each session it computes per-measurement
summary statistics: **min, max, avg, and median**.

Measurements are grouped by measurement type plus a compatible unit family,
reusing the same grouping the session export uses for replay analysis. This
means a mixed-mode session (e.g. voltage and current interleaved) contributes to
several trend series, one per measurement context.

### Mixed-unit handling

Sessions are normalized to a single display unit per trend series. If January's
inrush was captured in amps and July's in milliamps, both are converted to a
common base unit and the whole series is displayed in one unit (e.g. `A`), so the
trend is directly comparable session over session.

## Desktop

The **Assets** tab (between Workflows and Settings) provides:

- a table of tracked assets with linked-session counts
- a create/edit form (name, type, location, notes) and delete
- the selected asset's linked sessions
- a trend chart with:
  - a measurement selector (one entry per measurement type found across the
    asset's sessions)
  - a statistic selector (Minimum / Maximum / Average / Median)
  - x-axis = session date, y-axis = the chosen statistic
- **Export Trend CSV** and **Export Trend Chart** (PNG), matching the other
  chart export buttons in the app

Assign a session to an asset:

- **Live Reading tab**: pick an asset in the "Asset (optional)" selector before
  starting a session
- **Session tab**: select a recorded session, choose an asset in the "Asset"
  selector next to the recent-sessions list, and click **Assign Asset** (choose
  "No asset" to unlink)

## CLI

```powershell
# Create and inspect assets
fluke assets create --name "Line 3 Motor" --type motor --location "Bay 2"
fluke assets list
fluke assets show --asset <ASSET_ID>

# Attach sessions
fluke log --device "<DEVICE_ID>" --asset <ASSET_ID> --duration 30
fluke sessions assign-asset --session "<SESSION_ID>" --asset <ASSET_ID>
fluke sessions list --asset <ASSET_ID>

# Trend a piece of equipment
fluke assets trend --asset <ASSET_ID>
fluke assets trend --asset <ASSET_ID> --measurement current_inrush
fluke assets trend --asset <ASSET_ID> --csv-output exports/asset-trend.csv
```

`--database` is a group-level flag, so place it before the subcommand:

```powershell
fluke assets --database C:\path\to\fluke.db list
```

All list/show/trend commands support the global `--json` flag:

```powershell
fluke --json assets trend --asset <ASSET_ID> --measurement current_inrush
```

## Exports

The asset trend export writes one row per session per measurement group with its
statistics. Columns:

```text
asset_id, measurement, label, unit, session_id, session_title, started_at,
reading_count, numeric_count, min, max, avg, median
```

Available from:

- desktop **Assets** tab -> **Export Trend CSV**
- CLI `fluke assets trend --asset <ASSET_ID> --csv-output <PATH>`

## Data model and migration

Asset support was added in SQLite schema version 4:

- a new `assets` table
- a nullable `asset_id` column on `sessions` and on `workflow_runs`

Existing databases upgrade automatically and non-destructively: the new column
is added via the same additive `ALTER TABLE ... ADD COLUMN` mechanism used for
earlier schema changes, so old sessions keep working and remain unassigned.

## Related guides

- [CLI Guide](cli-guide.md)
- [Desktop User Guide](desktop-guide.md)
- [Data and Exports Guide](data-and-exports.md)
