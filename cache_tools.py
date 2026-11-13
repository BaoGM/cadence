# SPDX-License-Identifier: GPL-3.0-only
"""Remove only Cadence-generated cache entries, preserving sources and active media."""
from pathlib import Path
import os,re,stat
from media import cache_root

def linked(path):
    return path.is_symlink() or (os.name=='nt' and path.stat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)

def cache_entries():
    root=cache_root().resolve()
    for folder in root.iterdir():
        if not re.fullmatch('[0-9a-f]{24}',folder.name) or not folder.is_dir(): continue
        if linked(folder): continue
        if folder.resolve().parent!=root: continue
        files=list(folder.iterdir())
        allowed={'media.json','preview.avi','audio.s16','waveform-v1.npy'}
        if any(not p.is_file() or linked(p) or (p.name not in allowed and not re.fullmatch(r'(?:waveform-v1\.npy|media\.json)\.[0-9a-f]+\.tmp',p.name)) for p in files): continue
        yield folder,files

def clear_cache(protected=()):
    protected={Path(p).resolve().parent for p in protected if p}
    deleted=kept=failed=freed=0
    for folder,files in cache_entries():
        if folder in protected: kept+=1; continue
        try:
            size=sum(p.stat().st_size for p in files)
            # Delete the preview first: an open decoder normally locks this file.
            for path in sorted(files,key=lambda p:p.name!='preview.avi'): path.unlink()
            folder.rmdir(); deleted+=1; freed+=size
        except OSError: failed+=1
    return deleted,kept,failed,freed

def cache_bytes():
    try: return sum(p.stat().st_size for _,files in cache_entries() for p in files)
    except OSError: return 0
