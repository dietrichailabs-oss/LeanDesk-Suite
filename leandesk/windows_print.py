"""Windows WPF print dispatch without a registered RTF shell print verb."""
from __future__ import annotations

import base64
import atexit
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time

from .document_formats import LeanDocument, write_text_document


class PrintUnavailableError(RuntimeError):
    pass


_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
try {
    Add-Type -AssemblyName PresentationFramework
    Add-Type -AssemblyName ReachFramework
    $document = New-Object System.Windows.Documents.FlowDocument
    $range = New-Object System.Windows.Documents.TextRange($document.ContentStart, $document.ContentEnd)
    $stream = [IO.File]::OpenRead($env:LEANDESK_PRINT_RTF)
    try { $range.Load($stream, [System.Windows.DataFormats]::Rtf) }
    finally { $stream.Dispose() }
    $dialog = New-Object System.Windows.Controls.PrintDialog
    if ($dialog.ShowDialog() -ne $true) {
        @{status='cancelled'} | ConvertTo-Json -Compress
        exit 0
    }
    if ($null -eq $dialog.PrintQueue) { throw 'No printer is available.' }
    $document.PageWidth = $dialog.PrintableAreaWidth
    $document.PageHeight = $dialog.PrintableAreaHeight
    $document.PagePadding = New-Object System.Windows.Thickness(36)
    $document.ColumnWidth = $document.PageWidth
    $paginator = ([System.Windows.Documents.IDocumentPaginatorSource]$document).DocumentPaginator
    $dialog.PrintDocument($paginator, 'LeanDesk Writer document')
    @{status='submitted'} | ConvertTo-Json -Compress
} catch {
    $details = New-Object System.Collections.Generic.List[string]
    $exception = $_.Exception
    for ($depth = 0; $null -ne $exception -and $depth -lt 8; $depth++) {
        $details.Add(('{0}: {1} (HRESULT 0x{2:X8})' -f $exception.GetType().FullName, $exception.Message, $exception.HResult))
        if ($exception -is [System.Runtime.CompilerServices.RuntimeWrappedException]) {
            $details.Add([string]$exception.WrappedException)
        }
        $exception = $exception.InnerException
    }
    @{status='error'; message=($details -join ' -> ')} | ConvertTo-Json -Compress
    exit 1
}
'''


def _run_cancellable(command, environment, cancel_event, timeout=300):
    """Drain both pipes while keeping cancellation and timeout cleanup bounded."""
    if cancel_event.is_set():
        raise PrintUnavailableError("Printing was stopped before the dialog opened.")
    with subprocess.Popen(
        command, env=environment, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    ) as child:
        deadline = time.monotonic() + timeout
        try:
            while True:
                if cancel_event.is_set():
                    child.kill()
                    child.communicate()
                    raise PrintUnavailableError(
                        "Printing was interrupted. Submission was not confirmed; "
                        "check the printer queue before retrying."
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    child.kill()
                    stdout, stderr = child.communicate()
                    raise subprocess.TimeoutExpired(command, timeout, stdout, stderr)
                try:
                    stdout, stderr = child.communicate(timeout=min(0.1, remaining))
                    return subprocess.CompletedProcess(command, child.returncode, stdout, stderr)
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate()


class PrintJob:
    """Background printing with no Tk calls from the worker thread."""

    def __init__(self, document, *, owner=0, operation=None):
        self._cancel = threading.Event()
        self._done = threading.Event()
        self._result = None
        self._error = None
        operation = operation or print_rtf_document

        def run():
            try:
                self._result = operation(document, owner=owner, cancel_event=self._cancel)
            except Exception as exc:
                self._error = exc
            finally:
                self._done.set()
                atexit.unregister(self.close)

        self._thread = threading.Thread(target=run, name="LeanDesk-print", daemon=True)
        atexit.register(self.close)
        try:
            self._thread.start()
        except Exception:
            atexit.unregister(self.close)
            raise

    @property
    def done(self):
        return self._done.is_set()

    def cancel(self):
        self._cancel.set()

    def close(self):
        self.cancel()
        if threading.current_thread() is not self._thread:
            self._thread.join(5)

    def result(self):
        if not self.done:
            raise RuntimeError("Print job has not completed")
        if self._error is not None:
            if isinstance(self._error, PrintUnavailableError):
                raise self._error
            raise PrintUnavailableError(
                "Windows printing failed; submission was not confirmed. " + str(self._error)
            ) from self._error
        return self._result


def print_rtf_document(document: LeanDocument, *, owner: int = 0, cancel_event=None) -> str:
    """Open the Windows printer chooser; never silently select a printer."""
    if os.name != "nt":
        raise PrintUnavailableError("Printing requires Windows desktop printing support.")
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    if not powershell.is_file():
        raise PrintUnavailableError("Windows PowerShell and .NET desktop printing support are required. You can also export a PDF and print it in a PDF viewer.")
    try:
        with tempfile.TemporaryDirectory(prefix="LeanDesk_Print_") as directory:
            path = Path(directory) / "document.rtf"
            write_text_document(document, path)
            environment = os.environ.copy()
            environment["LEANDESK_PRINT_RTF"] = str(path)
            encoded = base64.b64encode(_SCRIPT.encode("utf-16le")).decode("ascii")
            command = [str(powershell), "-NoProfile", "-STA", "-EncodedCommand", encoded]
            if cancel_event is None:
                result = subprocess.run(
                    command, env=environment, capture_output=True, text=True, timeout=300,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                result = _run_cancellable(command, environment, cancel_event)
            reply = json.loads(result.stdout.strip())
            if not isinstance(reply, dict):
                raise PrintUnavailableError("Windows printing returned an invalid response; submission was not confirmed.")
            if result.returncode or reply.get("status") not in {"submitted", "cancelled"}:
                raise PrintUnavailableError("Windows could not submit the print job. Check that a printer (including Microsoft Print to PDF) is installed and available. " + str(reply.get("message", "")))
            return reply["status"]
    except subprocess.TimeoutExpired as exc:
        raise PrintUnavailableError("The print dialog timed out. No completion was confirmed; check the printer queue before retrying.") from exc
    except (OSError, ValueError, TypeError) as exc:
        raise PrintUnavailableError("Windows desktop printing could not be started. Your document is unchanged; you can export a PDF and print it in a PDF viewer.") from exc
