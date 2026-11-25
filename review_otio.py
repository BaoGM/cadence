# SPDX-License-Identifier: GPL-3.0-only
import json
from fractions import Fraction
from pathlib import Path

from review_csv import ReviewRow, save_bytes
from review_format import style_runs


def write_otio(path, doc, movie):
    rate=float(doc.fps)
    def span(start,duration):
        def time(value):
            return {'OTIO_SCHEMA':'RationalTime.1','rate':rate,'value':value}
        return {'OTIO_SCHEMA':'TimeRange.1','start_time':time(start),'duration':time(duration)}
    def item(schema, name, **fields):
        return dict(OTIO_SCHEMA=schema,name=name,metadata={},**fields)
    length=span(0,doc.state.length)
    movie=Path(movie).resolve()
    source=item('ExternalReference.1','',target_url=movie.as_uri(),available_range=length)
    clip=item('Clip.2',movie.stem,effects=[],markers=[],source_range=length,
              media_references={'DEFAULT_MEDIA':source},active_media_reference_key='DEFAULT_MEDIA')
    notes={f:(d,text) for f,d,text in doc.state.marker_notes}
    names=dict(doc.state.marker_names)
    styles=dict(doc.state.marker_styles)
    markers=[]
    for frame in doc.state.frame_markers:
        duration, text = notes.get(frame,(1,''))
        label=names.get(frame,'')
        marker=item('Marker.2',text or label,comment=text,color='ORANGE',marked_range=span(frame,duration))
        # RV preserves marker names, ranges and metadata when saving an OTIO.
        marker['metadata']['Cadence']={'name':label,'note':text}
        if frame in styles: marker['metadata']['Cadence']['styles']=styles[frame]
        markers.append(marker)
    audio=movie.suffix.lower() in ('.wav','.mp3')
    kind='Audio' if audio else 'Video'
    track=item('Track.1',kind,kind=kind,effects=[],markers=[] if audio else markers,source_range=None,children=[clip])
    stack=item('Stack.1','tracks',effects=[],markers=markers if audio else [],source_range=None,children=[track])
    timeline=item('Timeline.1',movie.stem,global_start_time=None,tracks=stack)
    save_bytes(path,json.dumps(timeline,ensure_ascii=False,indent=2).encode('utf-8'))


def read_otio(path,fps,length):
    def invalid():
        return ValueError('Timeline OpenTimelineIO invalide ou non prise en charge.')
    def seconds(time):
        if type(time['rate']) not in (int,float) or type(time['value']) not in (int,float):
            raise invalid()
        rate=Fraction(str(time['rate'])).limit_denominator(100000)
        if not 0<rate<=1000: raise invalid()
        return Fraction(str(time['value']))/rate
    def span(value):
        start=seconds(value['start_time'])
        return start,start+seconds(value['duration'])
    def schema(item):
        return item['OTIO_SCHEMA'].split('.')[0]
    def round_frame(seconds_):
        return (seconds_*fps+Fraction(1,2)).__floor__()
    rows=[]
    def add_markers(item,origin,visible):
        for marker in item.get('markers',[]):
            if schema(marker)!='Marker': raise invalid()
            start,end=span(marker['marked_range'])
            if end<start: raise invalid()
            if visible:
                if start==end and not visible[0]<=start<visible[1]: continue
                if start!=end and (end<=visible[0] or start>=visible[1]): continue
                start=max(start,visible[0])
                end=min(end,visible[1])
            frame=round_frame(origin+start)
            duration=max(1,round_frame(origin+end)-frame)
            if not 0<=frame<frame+duration<=length:
                raise ValueError('Les commentaires dépassent la durée du montage.')
            label=marker.get('name','')
            text=marker.get('comment','')
            saved=marker.get('metadata',{}).get('Cadence')
            styles=()
            if isinstance(saved,dict):
                original=saved['note'] or saved['name']
                text=(text or saved['note']) if label==original else label
                label=saved['name']
                if text==saved['note'] and 'styles' in saved:
                    styles=style_runs(saved['styles'],text)
            elif not text:
                text,label=label,''
            if not isinstance(label,str) or not isinstance(text,str): raise invalid()
            rows.append(ReviewRow(frame,duration,label,text,styles))
    with Path(path).open('rb') as stream:
        data=stream.read(16*1024*1024+1)
    if len(data)>16*1024*1024: raise ValueError('Fichier de commentaires trop volumineux.')
    try:
        timeline=json.loads(data)
        if schema(timeline)!='Timeline': raise invalid()
        stack=timeline['tracks']
        if schema(stack)!='Stack' or stack.get('source_range'): raise invalid()
        add_markers(stack,0,None)
        for track in stack['children']:
            if schema(track)!='Track' or track.get('source_range'): raise invalid()
            if track.get('kind')=='Audio': continue
            add_markers(track,0,None)
            playhead=Fraction(0)
            for clip in track['children']:
                if schema(clip) not in ('Clip','Gap'): raise invalid()
                if any(effect.get('OTIO_SCHEMA','').split('.')[0] in ('LinearTimeWarp','FreezeFrame','TimeEffect') for effect in clip.get('effects',[])): raise invalid()
                source=clip.get('source_range')
                if source is None and schema(clip)=='Clip':
                    reference=clip.get('media_reference') or clip['media_references'][clip['active_media_reference_key']]
                    source=reference.get('available_range')
                start,end=span(source)
                if end<start: raise invalid()
                add_markers(clip,playhead-start,(start,end))
                playhead+=end-start
    except (AttributeError,KeyError,TypeError,IndexError,ZeroDivisionError,OverflowError,RecursionError):
        raise invalid() from None
    if not rows: raise ValueError('Aucun marqueur à importer.')
    return rows
