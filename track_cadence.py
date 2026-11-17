# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from model import track_state,with_tracks
from cadence_change import plan_ranges,build_change


def plan_tracks(document,keys=None,span=None,spans=None,all_tracks=False):
    plans=[]
    for track in document.state.tracks if all_tracks else document.editable_tracks():
        state=track_state(document.state,track)
        ranges=plan_ranges(state,document.media,keys,span)
        if spans is not None:
            ranges=sorted({entry for selected in spans for entry in plan_ranges(state,document.media,span=selected)})
        if ranges: plans.append((track,ranges))
    return plans


def build_tracks(state,media,fps,plans,target,mode,pitch,quality,progress,cancel):
    updated=dict(media); outcomes={}
    all_selected=len(plans)==len(state.tracks)
    for index,(track,ranges) in enumerate(plans):
        single=track_state(state,track)
        single=replace(single,drawings_linked=state.drawings_linked and all_selected)
        changed,updated=build_change(single,updated,fps,ranges,target,mode,pitch,quality,
            lambda value,message:progress((index+value)/len(plans),message),cancel)
        outcomes[track.info.id]=changed
    combined=with_tracks(state,tuple(outcomes[t.info.id].tracks[0] if t.info.id in outcomes else t for t in state.tracks))
    leader=max(plans,key=lambda item:item[0].length)[0]
    changed=outcomes[leader.info.id]
    combined=replace(combined,position=min(changed.position,combined.length),selection=changed.selection,loop_range=changed.loop_range,
                     drawings=changed.drawings if all_selected else state.drawings,
                     frame_markers=changed.frame_markers if all_selected else state.frame_markers)
    return combined,updated
