"""Exercise the real Table dialog entry point, not just insert_table()."""

import tkinter as tk

import pytest

from leandesk.core import AppSettings, RecentFiles
from leandesk.writer import WriterFrame


@pytest.mark.parametrize("cancel_at", [0, 1, None])
def test_writer_table_dialog_open_cancel_and_accept(tmp_path, cancel_at):
    root = tk.Tk()
    root.withdraw()
    frame = WriterFrame(
        root, recent=RecentFiles(tmp_path / "recent.json"), settings=AppSettings()
    )
    frame.pack()
    observed = []
    callback_errors = []
    timed_out = []
    seen = set()
    scheduled = set()

    def schedule(delay, callback):
        token = None

        def run():
            scheduled.discard(token)
            callback()

        token = root.after(delay, run)
        scheduled.add(token)

    def cancel_scheduled():
        for token in list(scheduled):
            root.after_cancel(token)
            scheduled.discard(token)

    def dialogs(widget):
        for child in widget.winfo_children():
            if isinstance(child, tk.Toplevel):
                yield child
            else:
                yield from dialogs(child)

    def answer_dialog():
        try:
            for dialog in list(dialogs(root)):
                identity = str(dialog)
                if identity in seen or not dialog.winfo_viewable():
                    continue
                seen.add(identity)
                observed.append(dialog.title())
                index = len(observed) - 1
                if index == cancel_at:
                    dialog.cancel()
                else:
                    dialog.entry.delete(0, "end")
                    dialog.entry.insert(0, str((2, 3)[index]))
                    dialog.ok()
            schedule(50, answer_dialog)
        except Exception as exc:
            callback_errors.append(repr(exc))
            cancel_scheduled()
            root.destroy()

    def timeout():
        timed_out.append(True)
        cancel_scheduled()
        root.destroy()

    schedule(50, answer_dialog)
    schedule(5000, timeout)
    try:
        frame.insert_text_table()
        assert not timed_out, "Table dialog did not finish within five seconds"
        assert not callback_errors, callback_errors
        assert observed == ["Insert Table"] * (1 if cancel_at == 0 else 2)
        if cancel_at is None:
            assert len(frame.writer_objects) == 1
            table = next(iter(frame.writer_objects.values()))
            assert table["kind"] == "table"
            assert (table["rows"], table["cols"]) == (2, 3)
            assert table["data"] == [["", "", ""], ["", "", ""]]
        else:
            assert not frame.writer_objects
    finally:
        try:
            cancel_scheduled()
            root.destroy()
        except tk.TclError:
            pass
