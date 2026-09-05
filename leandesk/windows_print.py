"""Windows WPF print dispatch without a registered RTF shell print verb."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile

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
    @{status='error'; message=$_.Exception.Message} | ConvertTo-Json -Compress
    exit 1
}
'''


def print_rtf_document(document: LeanDocument, *, owner: int = 0) -> str:
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
            result = subprocess.run(
                [str(powershell), "-NoProfile", "-STA", "-EncodedCommand", encoded],
                env=environment, capture_output=True, text=True, timeout=300,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            reply = json.loads(result.stdout.strip())
            if result.returncode or reply.get("status") not in {"submitted", "cancelled"}:
                raise PrintUnavailableError("Windows could not submit the print job. Check that a printer (including Microsoft Print to PDF) is installed and available. " + str(reply.get("message", "")))
            return reply["status"]
    except subprocess.TimeoutExpired as exc:
        raise PrintUnavailableError("The print dialog timed out. No completion was confirmed; check the printer queue before retrying.") from exc
    except (OSError, ValueError, TypeError) as exc:
        raise PrintUnavailableError("Windows desktop printing could not be started. Your document is unchanged; you can export a PDF and print it in a PDF viewer.") from exc
