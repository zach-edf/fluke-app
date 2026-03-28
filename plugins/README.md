# Plugins

`plugins/` is the local discovery root for optional profile and workflow extensions.

The loader scans recursively for `manifest.json` files and, for each enabled plugin:

- imports the plugin module,
- calls its registration callable,
- loads any contributed device profiles,
- loads any contributed workflow JSON directories,
- exposes any fixture directories for contributor/debug workflows.

The main app, CLI, and SDK always ship with the built-in `fluke_376fc` profile. Plugins are additive.

## Layout

Use one folder per plugin:

```text
plugins/
  examples/
    example_profile_plugin/
      manifest.json
      profile.py
      workflows/
      fixtures/
```

## Manifest Fields

- `plugin_id`: stable unique id
- `name`: human-readable display name
- `version`: plugin version string
- `module`: Python file to import relative to the plugin root
- `callable`: optional registration function name, default `register_plugin`
- `description`: optional text shown in diagnostics
- `enabled`: optional boolean, default `true`
- `workflow_paths`: optional list of workflow JSON directories relative to the plugin root
- `fixture_paths`: optional list of fixture directories relative to the plugin root

## Registration Contract

The registration callable can return:

- `PluginRegistration`
- a `dict` with `profiles`, `workflow_paths`, `fixture_paths`
- a plain list of `DeviceProfile` instances

See `plugins/examples/example_profile_plugin/` for a disabled template.
