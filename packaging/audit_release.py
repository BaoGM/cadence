# SPDX-License-Identifier: GPL-3.0-only
import hashlib
import json
from pathlib import Path
import re
from fetch_ffmpeg import EXECUTABLE_SHA256


def audit(release):
    release=Path(release)
    runtime,=release.glob('_internal-[0-9]*')
    required=['Cadence.exe','_internal/vendor/ffmpeg.exe','_internal/native/bin/cadence_native.dll',
              '_internal/integrations/cadence_bridge.py',
              '_internal/integrations/cadence_autostart.py',
              '_internal/integrations/cadence_drawings.py',
              '_internal/integrations/cadence_drawings_blender.py',
              '_internal/integrations/cadence_drawings_maya.py',
              'Licences/Cadence-GPLv3.txt','Licences/Cadence-NOTICE.txt','Licences/Cadence-sources.zip',
              'Licences/THIRD-PARTY-SOURCES.txt','Licences/NOTICE.txt',
              'Licences/Qt/NOTICE.txt','Licences/Qt/Qt-notices.zip',
              'Licences/FFmpeg-export/LICENSE.txt','Licences/FFmpeg-export/READ-ME.txt',
              'Licences/av/THIRD-PARTY.txt','Licences/av/licenses/LICENSE.txt',
              'Licences/Python-LICENSE.txt']
    required += ['_internal/assets/'+name for name in ('cadence.ico','cadence.png','guide_fr.txt','guide_en.txt','ui_en.txt','ui_patterns.json','qtbase_fr.qm')]
    for name in required:
        path=release/name.replace('_internal/',runtime.name+'/')
        if not path.is_file(): raise FileNotFoundError(path)
    for path in release.rglob('*'):
        if path.is_symlink() or path.is_junction(): raise ValueError(f'Unexpected link: {path}')
        if path.name.lower() in ('demonstration.mp4','keyframepro.exe','resolve.exe','krita.exe','vlc.exe'):
            raise ValueError(f'Unexpected file: {path}')
        if any(part in ('imageio_ffmpeg','imageio-ffmpeg') or part.endswith('-sources') for part in path.parts):
            raise ValueError(f'Unexpected development bundle: {path}')
    reviewed=audit_assets(runtime/'assets')
    with (runtime/'vendor/ffmpeg.exe').open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=EXECUTABLE_SHA256: raise ValueError('Unexpected FFmpeg build')
    return {'status':'passed','runtime_resources':len(required),'reviewed_product_texts':reviewed,
            'third_party_notices_preserved':True,'demonstration_shipped':False}


def audit_assets(assets):
    forbidden=re.compile(r'keyframe\s*pro|zurbrigg|davinci|blackmagic|\bkrita\b|\bvlc\b|reverse.engineer',re.I)
    reviewed=[]
    for path in assets.iterdir():
        if path.suffix in ('.txt','.json'):
            content=path.read_text(encoding='utf-8')
            if path.name in ('guide_en.txt','guide_fr.txt'):
                content=content.replace('Keyframe Pro 2','')
            if forbidden.search(content): raise ValueError(f'Unexpected reference: {path}')
            reviewed.append(path.name)
    return reviewed


if __name__=='__main__':
    import sys
    print(json.dumps(audit(sys.argv[1]),indent=2))
