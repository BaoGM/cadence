# SPDX-License-Identifier: GPL-3.0-only
"""Per-user Windows association; no administrator rights or UserChoice override."""
import sys,ctypes
from pathlib import Path

VIDEO_EXTENSIONS=('.mp4','.mov','.avi','.mkv','.webm','.m4v','.mpg','.mpeg','.mts','.mxf','.gif','.wav','.mp3')

def registration_values(executable):
    exe=str(Path(executable).resolve())
    values={
        r'Software\Classes\Cadence.Studio2.Project': ('Cadence 2.0 (.cadence)',),
        r'Software\Classes\Cadence.Studio2.Project\DefaultIcon': (f'"{exe}",0',),
        r'Software\Classes\Cadence.Studio2.Project\shell\open\command': (f'"{exe}" "%1"',),
    }
    values.update({
        r'Software\Classes\Cadence.Studio2.Video': ('Cadence 2.0',),
        r'Software\Classes\Cadence.Studio2.Video\DefaultIcon': (f'"{exe}",0',),
        r'Software\Classes\Cadence.Studio2.Video\shell\open\command': (f'"{exe}" "%1"',),
    })
    return values

def register():
    if not getattr(sys,'frozen',False): raise RuntimeError('Lancez cette commande depuis la version .exe portable.')
    import winreg
    from update_store import base_executable
    executable=base_executable()
    for path,values in registration_values(executable).items():
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,path) as key: winreg.SetValueEx(key,'',0,winreg.REG_SZ,values[0])
    def value(path,name,data):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,path) as key: winreg.SetValueEx(key,name,0,winreg.REG_SZ,data)
    capabilities=r'Software\CadenceStudio2\Capabilities'
    value(capabilities,'ApplicationName','Cadence 2.0')
    value(capabilities,'ApplicationDescription','Cadence 2.0')
    value(capabilities,'ApplicationIcon',f'"{executable}",0')
    value(r'Software\RegisteredApplications','Cadence 2.0',capabilities)
    for extension in VIDEO_EXTENSIONS+('.cadence',):
        progid='Cadence.Studio2.Project' if extension=='.cadence' else 'Cadence.Studio2.Video'
        value(capabilities+r'\FileAssociations',extension,progid)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,'Software\\Classes\\'+extension+r'\OpenWithProgids') as key:
            winreg.SetValueEx(key,progid,0,winreg.REG_NONE,b'')
    ctypes.windll.shell32.SHChangeNotify(0x08000000,0,None,None)
