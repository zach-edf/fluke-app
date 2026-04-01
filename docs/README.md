# Documentation Guide

This directory is the user and developer documentation hub for the Fluke Community project.

If you are new to the repo, start with the guides below instead of reading the code or jumping straight into command help.

## Start Here

### New users

- [Getting Started](getting-started.md): installation, requirements, first launch, and a suggested first-use path
- [Desktop User Guide](desktop-guide.md): full walkthrough of the PySide6 desktop application
- [CLI Guide](cli-guide.md): command reference, examples, and common terminal workflows
- [Workflows Page Guide](workflows-page.md): detailed explanation of guided workflow execution and workflow creation
- [Data and Exports Guide](data-and-exports.md): where data is stored, what gets exported, and how export behavior works
- [SDK Guide](sdk-guide.md): using the Python API directly from code

### Developers and contributors

- [Developer Documentation](developer/README.md): contributor docs hub
- [Development Workflow](developer/development-workflow.md): local setup, run paths, and repo ownership boundaries
- [Testing Guide](developer/testing-guide.md): test structure, targeted commands, and verification expectations
- [Desktop UI Architecture](developer/desktop-ui-architecture.md): how the desktop runtime, presenter, views, and themes fit together
- [Architecture Overview](architecture.md): the shared stack, layers, and extension boundary
- [Support Matrix](support-matrix.md): supported devices, workflows, and platform status
- [Fixtures and Debug Bundles](developer/fixtures-and-debug.md): contributor diagnostics workflow
- [New Device Profile Guide](developer/new-device-profile.md): how to add a new device profile cleanly
- [Plugins Overview](../plugins/README.md): local plugin layout and workflow/profile extension contract

## Recommended Reading Order

If you want to learn the app from scratch:

1. [Getting Started](getting-started.md)
2. [Desktop User Guide](desktop-guide.md)
3. [Workflows Page Guide](workflows-page.md)
4. [Data and Exports Guide](data-and-exports.md)
5. [CLI Guide](cli-guide.md)
6. [SDK Guide](sdk-guide.md)

If you want to understand the repo structure after learning the app:

1. [Architecture Overview](architecture.md)
2. [Developer Documentation](developer/README.md)
3. [Support Matrix](support-matrix.md)
4. [Plugins Overview](../plugins/README.md)

## Documentation Scope

The current docs set is intended to answer four kinds of questions:

- How do I install and run the project?
- How do I use each user-facing feature in the desktop app, CLI, or SDK?
- Where does the app store data, and how do exports and workflow files work?
- Where should contributors look when they need to extend the codebase?

## Screenshots

Desktop screenshots used during development are stored in [docs/fluke-app-screenshots](fluke-app-screenshots).

They are helpful for visual context, but the written guides should be treated as the source of truth for behavior.
