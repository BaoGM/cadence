# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import ssl
import sys
root = Path(SPECPATH)
windows = sys.platform == 'win32'
native_name = 'cadence_native.dll' if windows else 'libcadence_native.so'

datas = [(str(root / 'assets' / name), 'assets') for name in (
    'cadence.ico', 'cadence.png', 'guide_fr.txt',
    'guide_en.txt', 'qtbase_fr.qm', 'ui_en.txt', 'ui_patterns.json')]
datas += [(str(root / 'assets' / 'fonts'), 'assets/fonts')]
datas += [(str(root / 'tests' / 'blender_fixture.py'), 'tests')]
datas += [(str(root / 'integrations' / 'cadence_bridge.py'), 'integrations')]
datas += [(str(root / 'integrations' / 'cadence_autostart.py'), 'integrations')]
datas += [(str(root / 'integrations' / name), 'integrations') for name in (
    'cadence_drawings.py', 'cadence_drawings_blender.py', 'cadence_drawings_maya.py')]
if windows:
    datas += [(str(root/'vendor'/'ffmpeg.exe'),'vendor')]
media_binaries = [] if windows else [(str(root/'vendor'/'ffmpeg'),'vendor')]


# Some Python distributions require an additional CA file when constructing SSLContext.
ssl_ca = Path(ssl.__file__).with_name('codex-rejected-cas.pem')
if ssl_ca.is_file():
    datas.append((str(ssl_ca), '.'))
ssl_binaries = []
if sys.platform == 'win32':
    for name in ('libssl-3-x64.dll', 'libcrypto-3-x64.dll'):
        library = Path(sys.base_prefix) / 'DLLs' / name
        if not library.is_file():
            raise FileNotFoundError(f'Python TLS dependency missing: {library}')
        ssl_binaries.append((str(library), '.'))

a = Analysis(
    [str(root / 'app.py')],
    pathex=[],
    binaries=[(str(root/'native'/'bin'/native_name),'native/bin'), *ssl_binaries, *media_binaries],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'pytest', 'imageio_ffmpeg'] + ([] if windows else ['pyaudiowpatch']),
    noarchive=False,
    optimize=0,
)
# Qt uses Windows ICU. Do not bundle incompatible ICU found on the build host PATH.
a.binaries = [b for b in a.binaries if Path(b[0]).name.lower() not in {'icuuc.dll', 'icudt78.dll'}]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Cadence',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(root / 'assets' / 'cadence.ico'),
    version=str(root / 'version_info.txt'),
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Cadence',
)

