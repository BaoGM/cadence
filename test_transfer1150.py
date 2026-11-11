# SPDX-License-Identifier: GPL-3.0-only
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QMessageBox

from integrations import cadence_drawings
from integrations.cadence_bridge import Bridge
from test_sync1120 import application, link, pump


def test_removal_requires_explicit_global_scope(monkeypatch,tmp_path):
    calls=[]
    monkeypatch.setattr(cadence_drawings,'module',lambda host:SimpleNamespace(clear=lambda:calls.append(host)))
    for scope in (None,'project','all',''):
        with pytest.raises(ValueError,match='scope'):
            cadence_drawings.execute('maya',dict(type='drawing_remove',request='test',scope=scope),tmp_path)
    assert not calls
    result=cadence_drawings.execute('maya',dict(type='drawing_remove',request='test',scope='all_cadence'),tmp_path)
    assert calls==['maya'] and result==dict(type='drawing_result',request='test',ok=True,removed=True)


def test_confirmed_removal_without_camera_and_sync_survives(application,link,monkeypatch):
    host=dict(frame=1.,start=1.,end=100.,fps=24.)
    bridge=Bridge('blender',lambda:dict(host),lambda frame:host.update(frame=frame))
    removed=[]
    monkeypatch.setattr(cadence_drawings,'module',lambda host:SimpleNamespace(cameras=lambda:[],clear=lambda:removed.append(host)))
    bridge.drawings=cadence_drawings
    def wait(predicate):pump(application,lambda:(bridge.tick(),predicate())[1])
    try:
        wait(lambda:link.drawing_removal and link.metadata is not None and link.last_position is not None)
        monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.StandardButton.No)
        link.remove_drawings();assert not removed and not link.drawing_request
        monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.StandardButton.Yes)
        link.remove_drawings();assert link.drawing_request
        wait(lambda:link.drawing_request is None)
        assert removed==['blender'] and not link.window.errors
        assert 'supprimés' in link.transfer_status
        link.window.seek(15);wait(lambda:host['frame']==16.)
        assert link.window.doc.state.selection==(10,40)
    finally:bridge.close()


def test_connection_change_during_confirmation_cancels(application,link,monkeypatch):
    link.metadata={'fps':24};link.drawing_removal=True
    token=link.token
    sent=[];link.send=lambda message:sent.append(message)
    def confirm(*args):
        link.token='another-scene-connection'
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox,'question',confirm)
    link.remove_drawings()
    assert not sent and not link.drawing_request
    link.token=token
