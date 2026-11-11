# SPDX-License-Identifier: GPL-3.0-only
from bisect import bisect_right
from fractions import Fraction
from pathlib import Path
from media import prepare_media,Cancelled


class ReferenceSequence:
    def __init__(self,entries=()):
        self.entries=list(entries); self.ends=[]; total=Fraction(0)
        for media in self.entries:
            total+=Fraction(media['frames'],1)/Fraction(media['fps']); self.ends.append(total)

    def locate(self,seconds):
        index=bisect_right(self.ends,seconds)
        if seconds<0 or index>=len(self.entries): return None
        start=self.ends[index-1] if index else Fraction(0); media=self.entries[index]
        return index,media,min(media['frames']-1,int((seconds-start)*Fraction(media['fps'])))


def snapshot(entries):
    return [{key:media.get(key) for key in ('path','fps','frames','width','height','cadence')} for media in entries]


def restore(document,quality,progress,cancel):
    config=document.review
    entries=config.get('references')
    if entries is None:
        path=config.get('reference')
        entries=[dict(path=path,fps=config.get('reference_fps'),cadence=config.get('reference_cadence'))] if isinstance(path,str) and path else []
    if not isinstance(entries,list) or any(not isinstance(entry,dict) or not isinstance(entry.get('path'),str) for entry in entries):
        raise ValueError('Liste de références invalide.')
    loaded=[]; warnings=[]; cache={}
    for index,entry in enumerate(entries):
        try:
            identity=(entry['path'],str(entry.get('fps')),repr(entry.get('cadence')))
            if identity not in cache:
                cache[identity]=prepare_media(entry['path'],entry.get('fps'),progress=lambda value,message:progress((index+value)/len(entries),message),cancel=cancel,quality=quality,cadence=entry.get('cadence'))
            loaded.append(cache[identity])
        except Cancelled: raise
        except Exception as error:
            warnings.append(entry['path']+' : '+(str(error).strip() or type(error).__name__))
            if type(entry.get('frames')) is int and entry['frames']>0:
                try: fps=Fraction(entry['fps'])
                except (ValueError,TypeError,ZeroDivisionError): continue
                if not 1<=fps<=240: continue
                width=entry.get('width'); height=entry.get('height')
                loaded.append(dict(entry,id='missing-reference-'+str(index),name=Path(entry['path']).name,available=False,
                    width=width if type(width) is int and 2<=width<=32768 else 640,
                    height=height if type(height) is int and 2<=height<=32768 else 360))
    document.reference_sequence=loaded
    document.reference_media=loaded[0] if loaded else None
    document.reference_warning='\n'.join(warnings)
