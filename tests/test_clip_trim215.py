# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from clip_trim import trim_media
from model import Document, Segment, State, locate
from test_drawing import application
from test_timeline200 import timeline, point, move_pointer
from test_tracks1170 import two_tracks


def test_trim_preserves_other_occurrences_tracks_and_annotations_after_reopen(tmp_path):
    doc, first, second = two_tracks()
    duplicate = Segment('a', 12, 30, cut_before=True, rotation=12)
    doc.state = replace(doc.state, segments=doc.state.segments + (duplicate,),
                        audio_segments=None, frame_markers=(56,), marker_notes=((56, 1, 'Fin'),))
    original = doc.state
    assert trim_media(doc, first, 'video', 1, True, 4, True)
    assert trim_media(doc, first, 'video', 1, False, -5, True)
    assert doc.state.segments == (original.segments[0], replace(duplicate, start=16, end=25))
    assert doc.state.tracks[1] == original.tracks[1]
    assert doc.state.audio == doc.state.segments and doc.state.marker_notes == original.marker_notes
    path = tmp_path / 'trim.cadence'
    doc.save(path)
    doc = Document.load(path)
    assert trim_media(doc, first, 'video', 1, True, -4, True)
    assert trim_media(doc, first, 'video', 1, False, 5, True)
    assert doc.state.segments == original.segments
    assert trim_media(doc, first, 'video', 1, True, -999, True)
    assert doc.state.segments[1].start == 0 and doc.state.segments[0] == original.segments[0]
    assert not trim_media(doc, first, 'video', 1, True, -1, True)


def test_trim_one_frame_limits_and_unlinked_audio():
    doc, track, _ = two_tracks()
    original = doc.state
    assert trim_media(doc, track, 'video', 0, False, -400, False)
    assert doc.state.segments == (Segment('a', 0, 1),)
    assert doc.state.tracks[0].length == 40
    assert doc.state.audio == original.audio
    assert not trim_media(doc, track, 'video', 0, False, -1, False)
    assert trim_media(doc, track, 'video', 0, False, 400, False)
    assert doc.state.segments == original.segments and doc.state.audio == original.audio
    assert doc.undo() and doc.state.segments == (Segment('a', 0, 1),)
    assert doc.undo() and doc.state == original
    assert doc.redo() and doc.state.segments[0].end == 1


def test_explicit_audio_trim_and_old_segment_at_track_end():
    doc, track, _ = two_tracks()
    clip = Segment('a', 4, 18)
    audio = replace(clip, muted=True)
    doc.state = replace(doc.state, segments=(clip,), audio_segments=(audio,))
    assert trim_media(doc, track, 'audio', 0, True, 3, True)
    assert doc.state.audio[-1].muted and doc.state.segments[-1].start == 7
    assert trim_media(doc, track, 'audio', 0, True, -3, True)
    assert trim_media(doc, track, 'video', 0, False, 999, False)
    assert doc.state.segments == (replace(clip, end=40),)
    assert doc.state.audio == (audio,)


@pytest.mark.parametrize('lane', ['audio','video'])
@pytest.mark.parametrize('target', [0,1])
def test_unlinked_trim_roundtrip_append_and_tail_playback(tmp_path, lane, target):
    from test_tracks1170 import media
    doc, first, second = two_tracks(30,30)
    identity = (first,second)[target]
    doc.select_track(identity)
    doc.append_media([media('c',20)])
    key = ('a','b')[target]
    source = doc.state.tracks[target]
    doc.state = replace(doc.state, position=49, selection=(40,50), frame_markers=(49,))
    assert trim_media(doc,identity,lane,0,False,-10,False)
    video,audio = doc.state.tracks[target].segments,doc.state.tracks[target].audio
    edited,untouched = (video,audio) if lane=='video' else (audio,video)
    assert edited == (Segment(key,0,20),source.segments[1])
    assert untouched == source.segments
    assert locate(edited,20)==('c',0) and locate(edited,45)[0] is None
    assert locate(untouched,45)==('c',15) and doc.state.length==50
    assert doc.state.position==49 and doc.state.frame_markers==(49,) and doc.state.selection==(40,50)
    path=tmp_path/'unequal.cadence'
    doc.save(path)
    reopened=Document.load(path)
    assert reopened.format_version()==22 and reopened.state==doc.state
    old_reader_data=reopened.to_data()
    old_reader_data['version']=21
    with pytest.raises(ValueError):
        Document.from_data(old_reader_data)
    assert trim_media(reopened,identity,lane,0,False,10,False)
    assert reopened.state.tracks[target].segments==reopened.state.tracks[target].audio==source.segments
    assert reopened.format_version()==16
    assert reopened.undo() and reopened.state==doc.state
    reopened.select_track(identity)
    reopened.append_media([media('d',4)])
    after=reopened.state.tracks[target]
    assert after.length==54 and locate(after.segments,50)==locate(after.audio,50)==('d',0)


def test_trim_preserves_saved_intentional_gaps(tmp_path):
    from test_tracks1170 import media
    doc=Document()
    doc.append_media([media('a',40)])
    original=(Segment(None,0,3),Segment('a',2,12),Segment(None,0,7))
    doc.state=replace(doc.state,segments=original,audio_segments=None)
    path=tmp_path/'legacy.cadence'
    doc.save(path)
    doc=Document.load(path)
    assert doc.format_version()==11
    assert trim_media(doc,'media-1','video',1,True,2,False)
    assert doc.state.segments==(original[0], Segment('a',4,12), original[2])
    assert doc.state.audio==original
    assert trim_media(doc,'media-1','video',1,True,-2,False)
    assert doc.state.segments==doc.state.audio==original and doc.format_version()==11


def test_session_and_edits_inside_an_audio_tail(tmp_path):
    from session import read_session,write_snapshot
    from test_tracks1170 import media
    doc=Document()
    doc.append_media([media(key,10) for key in ('a','b','c')])
    assert trim_media(doc,'media-1','video',0,False,-7,False)
    snapshot=tmp_path/'session.json'
    write_snapshot(snapshot,(doc.state,doc.media,doc.fps,{},None,True),{})
    raw,restored=read_session(snapshot)
    assert raw['document']['version']==22 and restored.state==doc.state
    restored.select(25,30)
    assert restored.copy()==5 and restored.clipboard==(Segment(None,0,5),)
    assert restored.audio_clipboard==(Segment('c',5,10),)
    assert restored.duplicate_range(25,30,30)
    assert restored.state.length==35 and locate(restored.state.audio,34)==('c',9)
    assert restored.undo() and restored.state.length==30
    assert restored.move_range(3,13,30)
    assert locate(restored.state.segments,20)==('b',0)
    assert locate(restored.state.audio,20)==('a',3)


def test_trim_selected_occurrence_and_preserve_free_ranges():
    doc = Document()
    doc.media = {'a': {'frames': 32}, 'b': {'frames': 32}}
    first = Segment('a', 0, 32)
    duplicate = replace(first, cut_before=True)
    doc.state = State((first, Segment('b', 0, 32), duplicate), selection=(0, 32),
                      selected_clips=(('media-1', 0, 32), ('media-1', 64, 96)))
    assert trim_media(doc, 'media-1', 'video', 0, True, 7, True)
    assert doc.state.selection == (0, 25)
    assert doc.state.selected_clips == (('media-1', 0, 25), ('media-1', 57, 89))
    assert doc.copy() == 57
    assert all(s.media == 'a' for s in doc.clipboard)
    assert doc.undo() and doc.state.selected_clips[0] == ('media-1', 0, 32)
    assert doc.redo() and doc.state.selected_clips[0] == ('media-1', 0, 25)
    assert doc.delete() and next(s for s in doc.state.segments if s.media).media == 'b'
    doc.undo()
    doc.select(11, 19)
    assert trim_media(doc, 'media-1', 'video', 1, True, 3, True)
    assert doc.state.selection == (11, 19) and not doc.state.selected_clips


@pytest.mark.parametrize('reversed_clip', [False, True])
def test_ripple_trim_between_neighbours_roundtrip(tmp_path, reversed_clip):
    from test_tracks1170 import media
    doc = Document()
    for key in ('a', 'b', 'c'):
        doc.append_media([media(key, 40)])
    identity = doc.active_track_id
    if reversed_clip:
        assert doc.reverse_clip(identity, 'video', 42, True)
    a, b, c = doc.state.segments
    assert trim_media(doc, identity, 'video', 1, True, 7, True)
    assert trim_media(doc, identity, 'video', 1, False, -9, True)
    assert doc.state.segments == (a, b.sliced(7,31), c)
    assert doc.state.audio == doc.state.segments
    assert doc.state.length == 104
    path = tmp_path / 'ripple.cadence'
    doc.save(path)
    doc = Document.load(path)
    assert trim_media(doc, identity, 'video', 1, False, 200, True)
    assert trim_media(doc, identity, 'video', 1, True, -200, True)
    assert doc.state.segments == doc.state.audio == (a, b, c)
    assert doc.state.length == 120


@pytest.mark.parametrize('side', ['left', 'right'])
def test_drag_media_edge_commit_once_and_cancel(timeline, side):
    t, doc = timeline
    original = doc.state
    def commit(*args):
        assert trim_media(doc, *args)
        t.set_document(doc.state, doc.media, 24)
    t.mediaTrimmed.connect(commit)
    left = side == 'left'
    start = point(t, 32 if left else 64) + QPoint(11 if left else -11, 0)
    end = point(t, 39 if left else 57) + QPoint(11 if left else -11, 0)
    QTest.mousePress(t, Qt.LeftButton, Qt.NoModifier, start)
    move_pointer(t, end, Qt.NoModifier)
    assert t.gesture == 'trim' and t.clip_trim.delta == (7 if left else -7)
    assert doc.state is original
    preview = t.clip_trim.displayed_track(t.active_media)
    assert [s.length for s in preview.segments] == ([32, 7, 25, 32] if left else [32, 25, 32])
    assert t.clip_trim.frame.position == (39 if left else 56)
    assert t.clip_trim.frame.source == (7 if left else 24)
    if left:
        assert locate(preview.segments, 38)[0] is None
        assert locate(preview.segments, 39) == ('b', 7)
        assert locate(preview.segments, 64) == ('c', 0)
    t.grab()
    assert t.cancel_pointer_edit()
    assert t.clip_trim.preview_track is None
    QTest.mouseRelease(t, Qt.LeftButton, Qt.NoModifier, end)
    assert doc.state is original and not doc.undo_stack
    QTest.mousePress(t, Qt.LeftButton, Qt.NoModifier, start)
    move_pointer(t, end, Qt.NoModifier)
    QTest.mouseRelease(t, Qt.LeftButton, Qt.NoModifier, end)
    assert len(doc.undo_stack) == 1 and doc.state.segments[0] == original.segments[0]
    assert doc.state.segments[-1] == original.segments[-1]
    assert next(s for s in doc.state.segments if s.media == 'b') == Segment('b', 7 if left else 0, 32 if left else 25)
    assert doc.undo() and doc.state == original


@pytest.mark.parametrize('reverse', [False, True])
def test_preview_extending_left_across_an_occupied_cut(reverse):
    from clip_trim import ClipTrim
    doc, identity, _ = two_tracks()
    first = Segment('a', 10, 18)
    middle = Segment('a', 10, 22, cut_before=True, reversed=reverse)
    last = Segment('a', 30, 34)
    doc.state = replace(doc.state, segments=(first, middle, last), audio_segments=None)
    track, lower = doc.state.tracks
    plan = ClipTrim.find(track, doc.media, 'video', 1, True, linked=False)
    for delta in (-3, -10):
        frame = max(0, 8 + delta)
        before = plan.apply(delta, preview=True)
        assert locate(before.segments, frame) == ('a', middle.source_frame(delta))
        assert before.audio == track.segments
        after = plan.apply(delta)
        assert after.segments[0] == first and after.segments[-1] == last
        assert after.audio == track.segments
        assert locate(after.segments, 8) == ('a', middle.source_frame(delta))
        assert not any(not item.media for item in after.segments)
    assert doc.state.tracks[1] == lower
