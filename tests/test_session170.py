# SPDX-License-Identifier: GPL-3.0-only
import json
from dataclasses import replace,asdict
from session import SnapshotEncoder,write_snapshot,read_session
from drawing import DrawingKey,Mark
from model import State,Segment,Document


def test_snapshot_reuses_unchanged_art_and_invalidates_edits(monkeypatch,tmp_path):
    import session
    original=session.encode_json;calls=[]
    def counted(value):
        if isinstance(value,DrawingKey): calls.append(value)
        return original(value)
    monkeypatch.setattr(session,'encode_json',counted)
    keys=tuple(DrawingKey(i,i+1,(Mark(points=((.5,.5,1),)),)) for i in range(1000))
    st=State((Segment(None,0,1000),),drawings=keys)
    encoder=SnapshotEncoder()
    assert json.loads(encoder.state(st))==json.loads(original(asdict(st)))
    assert len(calls)==1000
    calls.clear();changed=replace(st,position=590,selection=(1,900))
    assert json.loads(encoder.state(changed))==json.loads(original(asdict(changed)))
    assert not calls
    edited=replace(keys[23],marks=(replace(keys[23].marks[0],color='#abcdef'),))
    changed=replace(changed,drawings=keys[:23]+(edited,)+keys[24:])
    assert json.loads(encoder.state(changed))==json.loads(original(asdict(changed)))
    assert calls==[edited] and len(encoder.keys)==1000
    calls.clear();encoder.state(st);assert calls==[keys[23]]
    doc=Document();doc.state=changed
    path=tmp_path/'session.json'
    write_snapshot(path,(doc.state,doc.media,doc.fps,{},None,True),{'units':'time'},encoder)
    payload,restored=read_session(path)
    assert restored.state==changed and restored.dirty and payload['view']=={'units':'time'}
    assert not path.with_suffix('.json.tmp').exists()
