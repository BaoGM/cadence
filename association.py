# SPDX-License-Identifier: GPL-3.0-only
"""Per-user Windows association; no administrator rights or UserChoice override."""
import sys,ctypes
from pathlib import Path

VIDEO_EXTENSIONS=('.mp4','.mov','.avi','.mkv','.webm','.m4v','.mpg','.mpeg','.mts','.mxf','.gif','.wav','.mp3')

def registration_values(executable):
    exe=str(Path(executable).resolve())
    values={
        r'Software\Classes\CadenceStudio.Project': ('Cadence (.cadence)',),
        r'Software\Classes\CadenceStudio.Project\DefaultIcon': (f'"{exe}",0',),
        r'Software\Classes\CadenceStudio.Project\shell\open\command': (f'"{exe}" "%1"',),
    }
    values.update({
        r'Software\Classes\Cadence.Video': ('Cadence',),
        r'Software\Classes\Cadence.Video\DefaultIcon': (f'"{exe}",0',),
        r'Software\Classes\Cadence.Video\shell\open\command': (f'"{exe}" "%1"',),
        r'Software\Classes\Applications\Cadence.exe\shell\open\command': (f'"{exe}" "%1"',),
    })
    return values

def register():
    if not getattr(sys,'frozen',False): raise RuntimeError('Lancez cette commande depuis la version .exe portable.')
    import winreg
    for path,values in registration_values(sys.executable).items():
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,path) as key: winreg.SetValueEx(key,'',0,winreg.REG_SZ,values[0])
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Classes\.cadence') as key:
        # Do not replace an unrelated existing default.
        try: current=winreg.QueryValueEx(key,'')[0]
        except FileNotFoundError: current=''
        if not current or current=='CadenceStudio.Project': winreg.SetValueEx(key,'',0,winreg.REG_SZ,'CadenceStudio.Project')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Classes\.cadence\OpenWithProgids') as key:
        winreg.SetValueEx(key,'CadenceStudio.Project',0,winreg.REG_NONE,b'')
    def value(path,name,data):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,path) as key: winreg.SetValueEx(key,name,0,winreg.REG_SZ,data)
    app=r'Software\Classes\Applications\Cadence.exe'
    value(app,'FriendlyAppName','Cadence')
    capabilities=r'Software\Cadence\Capabilities'
    value(capabilities,'ApplicationName','Cadence')
    value(capabilities,'ApplicationDescription','Cadence')
    value(capabilities,'ApplicationIcon',f'"{sys.executable}",0')
    value(r'Software\RegisteredApplications','Cadence',capabilities)
    for extension in VIDEO_EXTENSIONS+('.cadence',):
        progid='CadenceStudio.Project' if extension=='.cadence' else 'Cadence.Video'
        value(app+r'\SupportedTypes',extension,'')
        value(capabilities+r'\FileAssociations',extension,progid)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,'Software\\Classes\\'+extension+r'\OpenWithProgids') as key:
            winreg.SetValueEx(key,progid,0,winreg.REG_NONE,b'')
    ctypes.windll.shell32.SHChangeNotify(0x08000000,0,None,None)
