# SPDX-License-Identifier: GPL-3.0-only
import os
from pathlib import Path
import re
import sys

from integrations.cadence_bridge import endpoint_path
from ui_text import tr


def write_changed(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding='utf-8') == text:
        return False
    temporary = path.with_suffix(path.suffix + '.cadence-tmp')
    temporary.write_text(text, encoding='utf-8')
    temporary.replace(path)
    return True


def blender_script_folders():
    override = os.environ.get('BLENDER_USER_SCRIPTS')
    if override:
        return [Path(override)]
    root = Path(os.environ.get('APPDATA', Path.home())) / 'Blender Foundation' / 'Blender'
    versions = {p.name for p in root.glob('*') if p.is_dir() and re.fullmatch(r'[4-9]\d*\.\d+', p.name)}
    installs = set((Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Blender Foundation').glob('Blender*'))
    import psutil
    for process in psutil.process_iter(['name', 'exe']):
        if (process.info['name'] or '').lower() == 'blender.exe' and process.info['exe']:
            installs.add(Path(process.info['exe']).parent)
    for folder in installs:
        versions.update(p.name for p in folder.glob('*') if p.is_dir() and re.fullmatch(r'[4-9]\d*\.\d+', p.name))
    if not versions:
        raise OSError(tr('Installation de Blender introuvable. Lancez Blender une fois, puis réessayez.'))
    return [root / version / 'scripts' for version in sorted(versions)]


def install_connector(host):
    if host not in ('blender', 'maya'):
        raise ValueError('Unsupported 3D application')
    source = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'integrations'
    runtime = endpoint_path().parent / 'integrations'
    for name in ('cadence_bridge.py', 'cadence_autostart.py', 'cadence_drawings.py',
                 'cadence_drawings_blender.py', 'cadence_drawings_maya.py'):
        write_changed(runtime / name, (source / name).read_text(encoding='utf-8'))
    loader = ("import importlib.util as _cadence_import, sys as _cadence_sys\n"
        "_cadence_module = _cadence_sys.modules.get('cadence_autostart')\n"
        "if _cadence_module is None:\n"
        f"    _cadence_spec = _cadence_import.spec_from_file_location('cadence_autostart', {str(runtime / 'cadence_autostart.py')!r})\n"
        "    _cadence_module = _cadence_import.module_from_spec(_cadence_spec)\n"
        "    _cadence_sys.modules['cadence_autostart'] = _cadence_module\n"
        "    _cadence_spec.loader.exec_module(_cadence_module)\n")
    changed = False
    if host == 'blender':
        text = loader + "\ndef register():\n    _cadence_module.start('blender')\n\ndef unregister():\n    _cadence_module.shutdown()\n"
        for folder in blender_script_folders():
            startup = folder / 'startup' / 'cadence_timeline_startup.py'
            changed |= not startup.exists()
            write_changed(startup, text)
    else:
        from PySide6.QtCore import QStandardPaths
        root = Path(os.environ.get('MAYA_APP_DIR') or (Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)) / 'maya'))
        module = runtime / 'maya'
        text = loader + "\nimport maya.cmds as _cadence_cmds\n_cadence_cmds.evalDeferred(\"import cadence_autostart; cadence_autostart.start('maya')\", lowestPriority=True)\n"
        setup = module / 'scripts' / 'userSetup.py'
        descriptor = root / 'modules' / 'cadence_timeline.mod'
        changed = not setup.exists() or not descriptor.exists()
        write_changed(setup, text)
        write_changed(descriptor, f'+ CadenceTimeline 1.15.1 {module.as_posix()}\n')
    return changed
