# SPDX-License-Identifier: GPL-3.0-only
import os
from pathlib import Path
import shutil
import subprocess
import sys

DESKTOP_ID = 'cadence.desktop'
PROJECT_MIME = 'application/x-cadence-project'
MIME_TYPES = (PROJECT_MIME, 'video/mp4', 'video/quicktime', 'video/x-msvideo',
              'video/x-matroska', 'video/webm', 'video/x-m4v', 'video/mpeg',
              'video/mp2t', 'application/mxf', 'image/gif', 'audio/x-wav', 'audio/mpeg')


def desktop_quote(value):
    value = str(value)
    if any(char in value for char in '\n\r\x00='):
        raise ValueError('Unsupported launcher path')
    value = ''.join('\\' + char if char in '\\"`$' else char for char in value)
    return '"' + value.replace('\\', '\\\\').replace('%', '%%') + '"'


def desktop_entry(executable):
    return ('[Desktop Entry]\nType=Application\nName=Cadence\n'
            f'Exec={desktop_quote(executable)} %f\nIcon=cadence\nTerminal=false\n'
            'Categories=AudioVideo;Video;\nMimeType=' + ';'.join(MIME_TYPES) + ';\n')


def register():
    if not getattr(sys, 'frozen', False):
        raise RuntimeError('Lancez cette commande depuis la version portable de Cadence.')
    commands = {name: shutil.which(name) for name in ('update-mime-database', 'update-desktop-database', 'xdg-mime')}
    if not all(commands.values()):
        raise RuntimeError('Installez xdg-utils, desktop-file-utils et shared-mime-info pour enregistrer les associations.')
    value = os.environ.get('XDG_DATA_HOME', '')
    data = Path(value) if value and Path(value).is_absolute() else Path.home() / '.local/share'
    applications, mime = data / 'applications', data / 'mime'
    package = mime / 'packages/cadence.xml'
    icon = data / 'icons/hicolor/256x256/apps/cadence.png'
    entry = desktop_entry(Path(sys.executable).resolve())
    for folder in (applications, package.parent, icon.parent): folder.mkdir(parents=True, exist_ok=True)
    package.write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
        '<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">\n'
        f'<mime-type type="{PROJECT_MIME}"><comment>Cadence project</comment>'
        '<glob pattern="*.cadence"/></mime-type>\n</mime-info>\n', encoding='utf-8')
    source = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'assets/cadence.png'
    shutil.copyfile(source, icon)
    (applications / DESKTOP_ID).write_text(entry, encoding='utf-8')
    env = os.environ.copy()
    # Desktop utilities must use the host libraries, not the frozen Qt runtime.
    if getattr(sys, 'frozen', False):
        env.pop('LD_LIBRARY_PATH', None)
        if env.get('LD_LIBRARY_PATH_ORIG'): env['LD_LIBRARY_PATH'] = env['LD_LIBRARY_PATH_ORIG']
    for name, directory in (('update-mime-database', mime), ('update-desktop-database', applications)):
        subprocess.run([commands[name], str(directory)], env=env, check=True, capture_output=True, timeout=20)
    return applications / DESKTOP_ID
