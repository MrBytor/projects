"""Best-effort, background read-only slide exports for local Windows development."""
import os
from pathlib import Path
import subprocess
import sys
from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from .curriculum import cached_fingerprint, cached_preview


def queue_presentation_preview(item):
    """Dispatch an exporter after commit; return immediately, preserving the upload."""
    if sys.platform != 'win32' or item.kind != 'file' or not item.file:
        return False
    try:
        source = Path(item.file.path).resolve()
        if source.suffix.lower() != '.pptx' or not source.is_relative_to((settings.DATA_DIR / 'content-files').resolve()) or not source.is_file():
            return False
        stat = source.stat()
        fingerprint = cached_fingerprint(source, stat.st_mtime_ns, stat.st_size)
        folder = settings.DATA_DIR / 'slide-previews' / fingerprint
        try:
            stat = (folder / 'manifest.json').stat()
            if cached_preview(folder, stat.st_mtime_ns, stat.st_size):
                return False
        except (OSError, ValueError, KeyError, TypeError):
            pass
        script = settings.BASE_DIR / 'render-presentations.ps1'
        powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
        env = os.environ.copy()
        env['TEACHING_DATA_DIR'] = str(settings.DATA_DIR)
        with (settings.DATA_DIR / 'slide-preview-jobs.log').open('ab') as log:
            subprocess.Popen(
                [str(powershell), '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                 '-File', str(script), '-PythonPath', sys.executable],
                cwd=str(settings.BASE_DIR), env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                shell=False, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
            )
        return True
    except (OSError, ValueError, SuspiciousFileOperation):
        # The download remains available; the launcher retries missing previews.
        return False
