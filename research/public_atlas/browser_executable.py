"""Locate Chrome or Chromium for both Atlas release checks."""
import os
from pathlib import Path
from shutil import which


def chrome_executable():
    if supplied := os.getenv('CHROME_BIN'):
        if path := which(supplied):
            return path
        raise FileNotFoundError(f'CHROME_BIN is not executable: {supplied}')
    for name in ('google-chrome', 'chromium', 'chromium-browser'):
        if path := which(name):
            return path
    paths = [Path(os.environ[key]) / 'Google/Chrome/Application/chrome.exe'
             for key in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA') if key in os.environ]
    paths.append(Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'))
    for path in paths:
        if path.is_file():
            return str(path)
    raise FileNotFoundError('Set CHROME_BIN to a Chrome or Chromium executable.')
