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
    changed = False
    for name in ('cadence_runtime.py', 'cadence_bridge.py', 'cadence_autostart.py', 'cadence_drawings.py',
                 'cadence_drawings_blender.py', 'cadence_drawings_maya.py'):
        changed |= write_changed(runtime / name, (source / name).read_text(encoding='utf-8'))
    runtime_path = 'u' + ascii(str(runtime / 'cadence_runtime.py'))
    auto_path = 'u' + ascii(str(runtime / 'cadence_autostart.py'))
    loader = (
        "def _cadence_startup():\n"
        "    try:\n"
        "        import sys\n"
        "        module = sys.modules.get('cadence_autostart')\n"
        "        if module is None:\n"
        "            import types\n"
        "            runtime = types.ModuleType('cadence_runtime')\n"
        f"            runtime.__file__ = {runtime_path}\n"
        "            runtime.__package__ = ''\n"
        "            sys.modules['cadence_runtime'] = runtime\n"
        "            with open(runtime.__file__, 'rb') as stream:\n"
        "                exec(compile(stream.read(), runtime.__file__, 'exec'), runtime.__dict__)\n"
        f"            module = runtime.load_source('cadence_autostart', {auto_path})\n")
    if host == 'maya':
        loader += ("        import maya.cmds as cmds\n"
            "        cmds.evalDeferred(\"import cadence_autostart; cadence_autostart.safe_start('maya')\", lowestPriority=True)\n")
    else:
        loader += "        module.safe_start('blender')\n"
    loader += (
        "    except (Exception, SystemExit):\n"
        "        try:\n"
        "            import logging\n"
        "            logging.getLogger('cadence.connector').exception('Cadence startup failed; other startup scripts are unaffected')\n"
        "        except Exception:\n"
        "            pass\n")
    if host == 'blender':
        text = loader + ("\ndef register():\n    _cadence_startup()\n\ndef unregister():\n"
            "    import sys\n    module = sys.modules.get('cadence_autostart')\n"
            "    if module is not None:\n        module.shutdown()\n")
        for folder in blender_script_folders():
            startup = folder / 'startup' / 'cadence_timeline_startup.py'
            changed |= write_changed(startup, text)
    else:
        from PySide6.QtCore import QStandardPaths
        root = Path(os.environ.get('MAYA_APP_DIR') or (Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)) / 'maya'))
        module = runtime / 'maya'
        text = loader + "\n_cadence_startup()\ndel _cadence_startup\n"
        setup = module / 'scripts' / 'userSetup.py'
        descriptor = root / 'modules' / 'cadence_timeline.mod'
        changed |= write_changed(setup, text)
        changed |= write_changed(descriptor, f'+ CadenceTimeline 1.17.0 {module.as_posix()}\n')
    return changed
