"""Focused external gates for the unfrozen printing correction."""
import subprocess
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from leandesk.writer import WriterFrame
from leandesk.windows_print import PrintJob, PrintUnavailableError, _run_cancellable


def test_writer_returns_before_print_dialog_and_reports_cancel_on_ui_poll():
    release = threading.Event()
    entered = threading.Event()
    callbacks = []
    statuses = []
    bindings = {}
    root = SimpleNamespace(winfo_id=lambda: 0)
    root.bind = lambda name, callback, add: bindings.setdefault("destroy", callback)
    root.unbind = lambda *args: bindings.clear()
    frame = SimpleNamespace(
        serialize=lambda: object(), winfo_toplevel=lambda: root,
        status_var=SimpleNamespace(set=statuses.append),
        after=lambda delay, callback: callbacks.append(callback),
    )

    def dialog(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return "cancelled"

    with patch("leandesk.writer.print_rtf_document", side_effect=dialog) as operation:
        try:
            WriterFrame.print_document(frame)
            assert entered.wait(1)
            assert not frame._print_job.done
            assert callbacks
            WriterFrame.print_document(frame)
            assert operation.call_count == 1
            job = frame._print_job
        finally:
            release.set()
        job._thread.join(2)
        callbacks.pop(0)()
        assert frame._print_job is None
        assert statuses[-1] == "Printing cancelled"
        assert not bindings


def test_print_job_cancellation_propagates_without_false_success():
    def operation(*args, cancel_event, **kwargs):
        assert cancel_event.wait(2)
        raise PrintUnavailableError("Submission unconfirmed")

    job = PrintJob(object(), operation=operation)
    job.close()
    assert job.done
    with pytest.raises(PrintUnavailableError, match="unconfirmed"):
        job.result()


@pytest.mark.parametrize("cancel", [True, False])
def test_child_is_reaped_after_cancel_or_timeout(cancel):
    event = threading.Event()

    class Child:
        returncode = None
        killed = False
        drained = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def poll(self):
            return self.returncode

        def kill(self):
            self.killed = True
            self.returncode = -1

        def communicate(self, timeout=None):
            if self.killed:
                self.drained = True
                return "", ""
            if cancel:
                event.set()
            else:
                time.sleep(0.02)
            raise subprocess.TimeoutExpired(["fake"], timeout)

    child = Child()
    expected = PrintUnavailableError if cancel else subprocess.TimeoutExpired
    with patch("leandesk.windows_print.subprocess.Popen", return_value=child):
        with pytest.raises(expected):
            _run_cancellable(["fake"], {}, event, timeout=0.01)
    assert child.killed and child.drained
