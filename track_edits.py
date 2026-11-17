# SPDX-License-Identifier: GPL-3.0-only
from copy import copy
from dataclasses import replace
from functools import wraps


def selected_tracks(operation):
    @wraps(operation)
    def edit(document,*args,**kwargs):
        from model import MediaTrack, Segment, with_tracks, track_state
        tracks=document.state.tracks
        targets=document.editable_tracks()
        if not targets: return 0 if operation.__name__ in ('copy','cut') else False
        if len(tracks)==1:
            result=operation(document,*args,**kwargs)
            if operation.__name__ in ('copy','cut') and result:
                document.track_clipboards={tracks[0].info.id:document.clipboard_state()}
            return result
        outcomes={}; copied={}; results=[]; all_selected=len(targets)==len(tracks)
        for target in targets:
            proxy=copy(document)
            proxy.state=track_state(document.state,target)
            proxy.state=replace(proxy.state,drawings_linked=document.state.drawings_linked and all_selected)
            proxy.undo_stack=[]; proxy.redo_stack=[]; proxy.track_clipboards={}
            proxy.selected_track_ids=(target.info.id,); proxy.active_track_id=target.info.id
            proxy.snap_destination=lambda frame,track='video':document.snap_destination(frame,track)
            if operation.__name__=='paste' and document.track_clipboards:
                clipboard=document.track_clipboards.get(target.info.id,next(iter(document.track_clipboards.values())))
                proxy.clipboard,proxy.audio_clipboard,proxy.drawing_clipboard,proxy.drawing_clipboard_length=clipboard
            required=0
            if operation.__name__ in ('paste','insert_gap'): required=document.state.position
            elif operation.__name__ in ('copy','cut'): required=document.selected()[1]
            elif operation.__name__ in ('move_range','duplicate_range'):
                required=max(int(value) for value in args[:3] if isinstance(value,(int,float))) if args else 0
            missing=max(0,required-target.length)
            if missing:
                gap=(Segment(None,0,missing),)
                proxy.state=replace(proxy.state,segments=target.segments+gap,audio_segments=target.audio+gap)
            result=operation(proxy,*args,**kwargs); results.append(result)
            if operation.__name__ in ('copy','cut') and result: copied[target.info.id]=proxy.clipboard_state()
            if proxy.undo_stack:
                outcomes[target.info.id]=(proxy.state.tracks[0],proxy.state,proxy.undo_stack[-1][0])
        if copied:
            document.track_clipboards=copied
            active=copied.get(document.active_track_id,next(iter(copied.values())))
            document.clipboard,document.audio_clipboard,document.drawing_clipboard,document.drawing_clipboard_length=active
        if outcomes:
            updated=with_tracks(document.state,tuple(outcomes[t.info.id][0] if t.info.id in outcomes else t for t in tracks))
            leader=max(targets,key=lambda t:t.length)
            _,changed,label=outcomes.get(leader.info.id,next(iter(outcomes.values())))
            updated=replace(updated,position=min(changed.position,max(0,updated.length-1)),
                            selection=changed.selection,loop_range=changed.loop_range,
                            drawings=changed.drawings if all_selected else document.state.drawings)
            document.commit(label,updated)
        if operation.__name__ in ('copy','cut'): return max(results,default=0)
        return bool(outcomes)
    return edit
