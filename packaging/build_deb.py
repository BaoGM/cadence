# SPDX-License-Identifier: GPL-3.0-only
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
from association_linux import DESKTOP_ID, desktop_entry, project_mime_xml

DEPENDENCIES = (
    'libc6 (>= 2.39)', 'libstdc++6 (>= 13.1)', 'libgcc-s1', 'libglib2.0-0t64',
    'libgl1', 'libegl1', 'libdbus-1-3', 'libfontconfig1', 'libfreetype6',
    'libx11-6', 'libx11-xcb1', 'libxkbcommon0', 'libxkbcommon-x11-0',
    'libxcb1', 'libxcb-cursor0', 'libxcb-icccm4', 'libxcb-image0',
    'libxcb-keysyms1', 'libxcb-randr0', 'libxcb-render0', 'libxcb-render-util0',
    'libxcb-shape0', 'libxcb-shm0', 'libxcb-sync1', 'libxcb-xfixes0', 'libxcb-xkb1',
    'xdg-utils', 'desktop-file-utils', 'shared-mime-info', 'pulseaudio-utils',
)


def build(version, payload, output, work):
    if sys.platform != 'linux':
        raise ValueError('Debian packages must be built on Linux')
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Expected major.minor.patch')
    if subprocess.check_output(['dpkg', '--print-architecture'], text=True).strip() != 'amd64':
        raise ValueError('The Linux runtime requires amd64')
    payload, output, work = Path(payload).resolve(), Path(output).resolve(), Path(work).resolve()
    for name in ('Cadence', '_internal/assets/cadence.png', 'Licences/Cadence-sources.zip'):
        if not (payload / name).is_file():
            raise FileNotFoundError(payload / name)
    if any(p.is_symlink() for p in payload.rglob('*')):
        raise ValueError('Package payload must not contain symlinks')
    work.mkdir(parents=True, exist_ok=False)
    runtime = work / 'opt/cadence'
    shutil.copytree(payload, runtime)
    (runtime / '.cadence-package').write_text('cadence-player\n', encoding='utf-8')

    def write(name, text):
        path = work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    write('usr/bin/cadence-player', '#!/bin/sh\nexec /opt/cadence/Cadence "$@"\n')
    write('usr/share/applications/' + DESKTOP_ID, desktop_entry('/usr/bin/cadence-player'))
    write('usr/share/mime/packages/cadence.xml', project_mime_xml())
    icon = work / 'usr/share/icons/hicolor/256x256/apps/cadence.png'
    icon.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(runtime / '_internal/assets/cadence.png', icon)
    write('usr/share/doc/cadence-player/copyright', (SOURCE / 'LICENSING.txt').read_text(encoding='utf-8') +
          '\nFull license texts and corresponding Cadence sources: /opt/cadence/Licences\n')
    files = sorted(p for p in work.rglob('*') if p.is_file())
    size = sum((p.stat().st_size + 1023) // 1024 for p in files)
    write('DEBIAN/control', f'Package: cadence-player\nVersion: {version}\nArchitecture: amd64\n'
          'Section: video\nPriority: optional\nMaintainer: Cadence contributors\n'
          f'Installed-Size: {size}\nDepends: ' + ', '.join(DEPENDENCIES) + '\n'
          'Homepage: https://cadenceplayer.org\n'
          'Description: Video review, drawing and editing for animation\n'
          ' Cadence provides frame-accurate playback, annotations, export and Blender\n'
          ' synchronization. This Linux beta targets Ubuntu Desktop 24.04 amd64.\n')
    write('DEBIAN/md5sums', ''.join(
        hashlib.md5(p.read_bytes(), usedforsecurity=False).hexdigest() + '  ' + p.relative_to(work).as_posix() + '\n'
        for p in files))
    refresh = ('#!/bin/sh\nset -e\n'
               'if command -v update-desktop-database >/dev/null 2>&1; then\n'
               '    update-desktop-database /usr/share/applications || true\nfi\n'
               'if command -v update-mime-database >/dev/null 2>&1; then\n'
               '    update-mime-database /usr/share/mime || true\nfi\n'
               'if command -v gtk-update-icon-cache >/dev/null 2>&1; then\n'
               '    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true\nfi\n')
    write('DEBIAN/postinst', refresh)
    write('DEBIAN/postrm', refresh)
    executables = {'opt/cadence/Cadence', 'opt/cadence/_internal/vendor/ffmpeg',
                   'usr/bin/cadence-player', 'DEBIAN/postinst', 'DEBIAN/postrm'}
    work.chmod(0o755)
    for path in work.rglob('*'):
        path.chmod(0o755 if path.is_dir() or path.relative_to(work).as_posix() in executables else 0o644)
    subprocess.run(['desktop-file-validate', str(work / 'usr/share/applications' / DESKTOP_ID)], check=True)
    output.mkdir(parents=True, exist_ok=True)
    result = output / f'Cadence-{version}-Linux-amd64.deb'
    subprocess.run(['dpkg-deb', '--root-owner-group', '-Zxz', '--build', str(work), str(result)], check=True)
    return result
