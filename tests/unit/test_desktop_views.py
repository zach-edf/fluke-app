from __future__ import annotations

import unittest

from apps.desktop.views import _sync_list_rows


class _FakeListItem:
    def __init__(self, text: str) -> None:
        self._text = text
        self._data = {}

    def setData(self, role: int, value: object) -> None:
        self._data[role] = value

    def data(self, role: int) -> object | None:
        return self._data.get(role)

    def text(self) -> str:
        return self._text


class _FakeListWidget:
    def __init__(self) -> None:
        self._items: list[_FakeListItem] = []

    def count(self) -> int:
        return len(self._items)

    def item(self, index: int) -> _FakeListItem:
        return self._items[index]

    def clear(self) -> None:
        self._items.clear()

    def addItem(self, item: _FakeListItem) -> None:
        self._items.append(item)


class DesktopViewsTests(unittest.TestCase):
    def test_sync_list_rows_refreshes_when_text_changes_for_same_id(self) -> None:
        widget = _FakeListWidget()

        _sync_list_rows(widget, _FakeListItem, [("run-1", "Battery Pack Check | 23:59 UTC | In Progress")])
        self.assertEqual(widget.count(), 1)
        self.assertEqual(widget.item(0).data(0x0100), "run-1")
        self.assertEqual(widget.item(0).text(), "Battery Pack Check | 23:59 UTC | In Progress")

        _sync_list_rows(widget, _FakeListItem, [("run-1", "Battery Pack Check | 23:59 UTC | Completed")])
        self.assertEqual(widget.count(), 1)
        self.assertEqual(widget.item(0).data(0x0100), "run-1")
        self.assertEqual(widget.item(0).text(), "Battery Pack Check | 23:59 UTC | Completed")


if __name__ == "__main__":
    unittest.main()
