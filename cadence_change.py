# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from fractions import Fraction
from bisect import bisect_right
from model import Segment,slice_segments,compact
from drawing import Mark,DrawingKey,slice_keys


def rate(value):
    text=str(value).strip().replace(',','.')
    aliases={'23.976':'24000/1001','29.97':'30000/1001','59.94':'60000/1001'}
    result=Fraction(aliases.get(text,text))
    if not 1<=result<=240: raise ValueError('La cadence doit être comprise entre 1 et 240 images/s.')
    return result


def settings(value):
    if value is None: return None
    if not isinstance(value,dict): raise ValueError('Réglage de cadence invalide.')
    speed=Fraction(value.get('speed','1'))
    if not Fraction(1,40)<=speed<=20: raise ValueError('La vitesse doit être comprise entre 2,5 % et 2 000 %.')
    pitch=value.get('preserve_pitch',True)
    if type(pitch) is not bool: raise ValueError('Réglage audio invalide.')
    return dict(rate=str(rate(value['rate'])),speed=str(speed),preserve_pitch=pitch)


def media_speed(media): return Fraction(media.get('cadence',{}).get('speed','1'))


def video_filter(fps,recipe=None):
    recipe=settings(recipe)
    if recipe is None: return f'setpts=PTS-STARTPTS,fps={fps}'
    speed=Fraction(recipe['speed'])
    return f'setpts=(PTS-STARTPTS)*{speed.denominator}/{speed.numerator},fps={recipe["rate"]}:round=near:eof_action=pass,fps={fps}:round=near:eof_action=pass'


def audio_filter(recipe):
    recipe=settings(recipe)
    speed=Fraction(recipe['speed']) if recipe else Fraction(1)
    if speed==1: return ''
    if not recipe['preserve_pitch']: return f',asetrate=48000*{speed.numerator}/{speed.denominator},aresample=48000'
    filters=[]
    while speed>2: filters.append('atempo=2'); speed/=2
    while speed<Fraction(1,2): filters.append('atempo=0.5'); speed*=2
    filters.append(f'atempo={float(speed):.12g}')
    return ','+','.join(filters)


def rounded(value):
    value=Fraction(value)
    return (2*value.numerator+value.denominator)//(2*value.denominator)


def change_ratio(media,target,mode):
    if mode=='duration': return Fraction(1)
    if mode!='speed': raise ValueError('Mode de cadence invalide.')
    return media_speed(media)/(rate(target)/Fraction(media.get('original_fps',media['fps'])))


def plan_ranges(state,media,keys=None,span=None):
    ranges=[]; at=0
    for seg in state.segments:
        end=at+seg.length
        if seg.media is not None and media[seg.media].get('has_video',True):
            if (keys is not None and seg.media in keys) or (span is not None and at<span[1] and end>span[0]):
                a,b=(max(at,span[0]),min(end,span[1])) if span else (at,end)
                ranges.append((a,b,seg.media))
        at=end
    return ranges


def build_change(state,media,fps,ranges,target,mode,preserve_pitch,quality,progress,cancel):
    from media import prepare_media,Cancelled
    target=rate(target); variants={}; requests={}; plans=[]
    if not ranges or any(not 0<=a<b<=state.length for a,b,_ in ranges) or any(left[1]>right[0] for left,right in zip(ranges,ranges[1:])):
        raise ValueError('Plages de cadence invalides.')
    for a,b,key in ranges:
        ratio=change_ratio(media[key],target,mode); plans.append((a,b,max(1,rounded((b-a)*ratio)),ratio))
        video_ids={s.media for s in slice_segments(state.segments,a,b)}
        for is_video,track in ((True,state.segments),(False,state.audio)):
            for seg in slice_segments(track,a,b):
                if seg.media is None: continue
                old=media[seg.media]; previous=old.get('cadence',{})
                recipe=settings(dict(rate=str(target) if is_video or seg.media in video_ids else previous.get('rate',old.get('original_fps',old['fps'])),speed=str(media_speed(old)/ratio),preserve_pitch=preserve_pitch if mode=='speed' else previous.get('preserve_pitch',True)))
                if not is_video and seg.media not in video_ids and ratio==1: continue
                requests[(seg.media,str(ratio),is_video)]=recipe
    for index,(identity,recipe) in enumerate(requests.items()):
        if cancel.is_set(): raise Cancelled()
        old=media[identity[0]]
        found=prepare_media(old['path'],fps,lambda value,message:progress((index+value)/max(1,len(requests)),message),cancel,quality=quality,cadence=recipe)
        variants[identity]=found
    updated=dict(media)
    for value in variants.values(): updated[value['id']]=value
    def transform(track,is_video):
        pieces=[]; cursor=0
        for a,b,length,ratio in plans:
            pieces.extend(slice_segments(track,cursor,a)); local=0
            for seg in slice_segments(track,a,b):
                end=local+seg.length; size=rounded(Fraction(end*length,b-a))-rounded(Fraction(local*length,b-a)); local=end
                if not size: continue
                variant=variants.get((seg.media,str(ratio),is_video))
                if seg.media is None: pieces.append(Segment(None,0,size)); continue
                if variant is None: pieces.append(seg); continue
                start=rounded(seg.start*ratio); start=max(0,min(start,variant['frames']-size))
                used=min(size,variant['frames']-start)
                pieces.append(replace(seg,media=variant['id'],start=start,end=start+used))
                if used<size: pieces.append(Segment(None,0,size-used))
            cursor=b
        pieces.extend(slice_segments(track,cursor,state.length)); return compact(tuple(pieces))
    ends=[]; deltas=[]; delta=0
    for a,b,length,ratio in plans:
        ends.append(b); delta+=length-(b-a); deltas.append(delta)
    def warp(frame):
        index=bisect_right(ends,frame); offset=deltas[index-1] if index else 0
        if index<len(plans):
            a,b,length,_=plans[index]
            if frame>=a: return a+offset+rounded(Fraction((frame-a)*length,b-a))
        return frame+offset
    video=transform(state.segments,True); audio=transform(state.audio,False); length=sum(s.length for s in video)
    if sum(s.length for s in audio)!=length: raise ValueError('Durées audio et vidéo incohérentes.')
    keys=[]; collision=False
    if state.drawings_linked:
        for key in state.drawings:
            start=min(length-1,warp(key.start)); end=min(length,max(start+1,warp(key.end)))
            if start<0 or start>=end: continue
            mapped=DrawingKey(start,end,key.marks)
            if keys and keys[-1].end>start:
                previous=keys.pop()
                grouped=previous.marks if collision else ((Mark(tool='group',points=((0.,0.,1.),),children=previous.marks),) if previous.marks else ())
                if mapped.marks: grouped+=(Mark(tool='group',points=((0.,0.,1.),),children=mapped.marks),)
                keys.append(DrawingKey(previous.start,max(previous.end,end),grouped))
                collision=True
            else: keys.append(mapped); collision=False
    else: keys=list(slice_keys(state.drawings,0,length))
    def selection(value):
        if value is None: return None
        a,b=map(warp,value); return (a,b) if a<b else None
    new=replace(state,segments=video,audio_segments=audio,drawings=tuple(keys),position=min(length,warp(state.position)),selection=selection(state.selection),loop_range=selection(state.loop_range),frame_markers=tuple(sorted(set(min(length-1,warp(f)) for f in state.frame_markers))))
    return new,updated
