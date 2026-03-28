from __future__ import annotations

from dataclasses import dataclass

from apps.desktop.presenters import AppPresenter


@dataclass(slots=True)
class DesktopRuntime:
    presenter: AppPresenter


def build_runtime() -> DesktopRuntime:
    return DesktopRuntime(presenter=AppPresenter())

