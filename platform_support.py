# SPDX-License-Identifier: GPL-3.0-only
import os
from pathlib import Path
import sys
import tempfile

WINDOWS = sys.platform == 'win32'


def xdg_directory(variable, fallback):
    value = os.environ.get(variable)
    root = Path(value) if value and Path(value).is_absolute() else Path.home() / fallback
    return root / 'CadenceStudio'


def config_directory():
    if WINDOWS:
        return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CadenceStudio'
    return xdg_directory('XDG_CONFIG_HOME', '.config')


def cache_directory():
    if WINDOWS:
        return Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'CadenceStudio' / 'cache'
    return xdg_directory('XDG_CACHE_HOME', '.cache')


def state_directory():
    if WINDOWS:
        return config_directory()
    return xdg_directory('XDG_STATE_HOME', '.local/state')
