# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace

from PySide6.QtWidgets import QInputDialog

from model import Document, Segment, State
from session import read_session, write_snapshot
from test_drawing import application, window


def test_marker_name_roundtrip_undo_session_and_removal(tmp_path):
    doc = Document()
    doc.state = State(segments=(Segment(None, 0, 24),), frame_markers=(2, 16))
    old = doc.to_data()
    old['state'].pop('marker_names')
    assert old['version'] == 12
    doc = Document.from_data(old)
    assert doc.rename_marker(2, '  Entrée caméra  ') and doc.dirty
    assert not doc.rename_marker(5, 'Absent')
    assert doc.undo() and not doc.dirty
    assert doc.redo()
    project = tmp_path / 'animation.cadence'
    doc.save(project)
    restored = Document.load(project)
    assert restored.state.marker_names == ((2, 'Entrée caméra'),)
    assert restored.format_version() == 17
    session = tmp_path / 'last_session.json'
    write_snapshot(session,(doc.state,doc.media,doc.fps,doc.review,str(project),False),{})
    assert read_session(session)[1].state == doc.state
    assert doc.rename_marker(2, ' ') and doc.format_version() == 12
    doc.undo()
    doc.commit('delete',replace(doc.state,frame_markers=(16,)))
    assert not doc.state.marker_names
    doc.undo()
    assert doc.state.marker_names == restored.state.marker_names


def test_rename_from_timeline_respects_cancel(window, monkeypatch):
    doc = window.doc
    doc.commit('mark',replace(doc.state,frame_markers=(4,)))
    window.refresh()
    monkeypatch.setattr(QInputDialog,'getText',lambda *a,**kw:('Contact',True))
    window.timeline.renameMarker.emit(4)
    assert doc.state.marker_names == ((4,'Contact'),)
    monkeypatch.setattr(QInputDialog,'getText',lambda *a,**kw:('Abandonné',False))
    window.timeline.renameMarker.emit(4)
    assert doc.state.marker_names == ((4,'Contact'),)
