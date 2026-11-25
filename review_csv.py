# SPDX-License-Identifier: GPL-3.0-only
import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path

from review_format import style_runs, text_units

from PySide6.QtCore import QIODevice, QSaveFile


@dataclass(frozen=True)
class ReviewRow:
    start: int
    duration: int
    name: str
    note: str
    styles: tuple = ()


def source_fps(value):
    value=str(value).strip().replace(',','.')
    if not re.fullmatch(r'[0-9]{1,7}(?:/[0-9]{1,7}|\.[0-9]{1,12})?',value):
        raise ValueError('Cadence source invalide.')
    try:
        rate=Fraction(value)
    except ZeroDivisionError:
        raise ValueError('Cadence source invalide.') from None
    if not 1<=rate<=240:
        raise ValueError('Cadence source invalide.')
    return rate


def frame_number(value, rate):
    value = value.strip()
    if re.fullmatch(r'-?[0-9]{1,10}', value):
        return int(value)
    match = re.fullmatch(r'(\d{1,3}):(\d{2}):(\d{2})([:;])(\d{2,3})', value)
    if not match:
        raise ValueError('Numéro d’image ou timecode invalide.')
    h, m, s, sep, f = match.groups()
    h, m, s, f = map(int,(h,m,s,f))
    nominal = round(rate)
    if m >= 60 or s >= 60 or f >= nominal:
        raise ValueError('Numéro d’image ou timecode invalide.')
    result = ((h * 60 + m) * 60 + s) * nominal + f
    if sep == ';':
        if rate not in (Fraction(30000,1001), Fraction(60000,1001)):
            raise ValueError('Cadence incompatible avec le timecode drop-frame.')
        minutes = h * 60 + m
        dropped = 2 if nominal == 30 else 4
        if m % 10 and s == 0 and f < dropped:
            raise ValueError('Numéro d’image ou timecode invalide.')
        result -= dropped * (minutes - minutes // 10)
    return result


def write_csv(path, doc):
    fields = ('Frame', 'Notes', 'Duration', 'Subject', 'FPS')
    styles=dict(doc.state.marker_styles)
    if styles: fields+=('Cadence Styles',)
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(fields)
    notes = {f:(d,text) for f,d,text in doc.state.marker_notes}
    names = dict(doc.state.marker_names)
    for frame in doc.state.frame_markers:
        duration, text = notes.get(frame,(1,''))
        row=(frame+1,text,duration,names.get(frame,''),str(doc.fps))
        if styles:
            payload={'for':hashlib.sha256(text.encode('utf-8')).hexdigest(),'runs':styles[frame]} if frame in styles else None
            row+=(json.dumps(payload,separators=(',',':')) if payload else '',)
        writer.writerow(row)
    save_bytes(path,stream.getvalue().encode('utf-8-sig'))


def save_bytes(path,data):
    output = QSaveFile(str(path))
    if not output.open(QIODevice.WriteOnly) or output.write(data)!=len(data) or not output.commit():
        raise OSError(output.errorString())


def load_csv(path):
    with Path(path).open('rb') as source:
        data = source.read(8*1024*1024+1)
    if len(data)>8*1024*1024:
        raise ValueError('Fichier de commentaires trop volumineux.')
    reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig'),newline=''),strict=True)
    header = set(reader.fieldnames or ())
    if {'Frame','Notes','Duration','Subject','FPS'} <= header:
        kind='cadence'
    elif {'Frame Number','Comment','Item Name'} <= header:
        kind='syncsketch'
    elif {'Start Frame','End Frame','Notes','Subject'} <= header:
        kind='xstudio'
    elif {'Frame','Notes'} <= header:
        kind='frame'
    else:
        raise ValueError('Colonnes de commentaires non reconnues.')
    rows = list(reader)
    if not rows or any(None in row or None in row.values() for row in rows):
        raise ValueError('Fichier de commentaires vide ou incomplet.')
    return kind, rows


def map_rows(kind, rows, fps, length, *, source_rate=None, origin=1, destination=0):
    mapped=[]
    for row in rows:
        try:
            rate=source_fps(row['FPS']) if kind=='cadence' else source_fps(source_rate if source_rate is not None else fps)
            if kind=='syncsketch':
                start=frame_number(row['Frame Number'],rate)
                duration, name, text=1,'',row['Comment']
            elif kind=='xstudio':
                start=frame_number(row['Start Frame'],rate)
                duration=frame_number(row['End Frame'],rate)-start+1
                name, text=row['Subject'],row['Notes']
            else:
                start=frame_number(row['Frame'],rate)
                duration=int(row.get('Duration',1))
                name, text=row.get('Subject',''),row['Notes']
            origin_frame=frame_number(str(origin),rate)
            if duration<=0 or start<origin_frame:
                raise ValueError
            def convert(frame):
                # Round time boundaries to nearest frame; resolve exact halves forward.
                return destination+int((frame-origin_frame)*fps/rate+Fraction(1,2))
            target=convert(start)
            end=max(target+1,convert(start+duration))
            if not 0<=target<end<=length:
                raise ValueError
            styles=()
            if kind=='cadence' and row.get('Cadence Styles'):
                payload=json.loads(row['Cadence Styles'])
                if not isinstance(payload,dict): raise ValueError
                if payload.get('for')==hashlib.sha256(text.encode('utf-8')).hexdigest():
                    styles=style_runs(payload.get('runs'),text)
            mapped.append(ReviewRow(target,end-target,name.strip(),text,styles))
        except (ValueError,ZeroDivisionError,OverflowError,RecursionError):
            raise ValueError('Vérifiez la cadence, la première image et la durée du montage.') from None
    return mapped


def merge_rows(doc,rows):
    state=doc.state
    frames=set(state.frame_markers)
    names=dict(state.marker_names)
    notes={f:(d,text) for f,d,text in state.marker_notes}
    styles=dict(state.marker_styles)
    for row in rows:
        frame=row.start
        frames.add(frame)
        if row.name:
            old=names.get(frame,'')
            if row.name!=old and row.name not in old.split(' / '):
                names[frame]=' / '.join(filter(None,(old,row.name)))
        duration,body=notes.get(frame,(1,''))
        if row.note and '\n\n'+row.note+'\n\n' not in '\n\n'+body+'\n\n':
            if row.styles:
                offset=text_units(body)+2 if body else 0
                styles[frame]=(*styles.get(frame,()),*((a+offset,b+offset,mask) for a,b,mask in row.styles))
            body='\n\n'.join(filter(None,(body,row.note)))
        elif row.styles and row.note==body:
            styles[frame]=row.styles
        if body or max(duration,row.duration)>1:
            notes[frame]=(max(duration,row.duration),body)
    return doc.commit('Importer les commentaires',replace(state,frame_markers=tuple(sorted(frames)),
        marker_styles=tuple(sorted(styles.items())), marker_names=tuple(sorted(names.items())), marker_notes=tuple((f,d,text) for f,(d,text) in sorted(notes.items()))))
