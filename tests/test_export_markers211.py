# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from pathlib import Path
import json
import time

import av
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit, QMessageBox

from media import prepare_media, run_ffmpeg
from model import Segment, State
from review_csv import ReviewRow, load_csv, map_rows
from review_otio import read_otio
from review_panel import CommentExportDialog, offer_rendered_markers
from test_drawing import application, window
from ui_text import tr


@pytest.mark.parametrize(('render_format','note_format'), [('mp4','csv'),('wav','otio'),('mp4','otio')])
def test_export_offers_markers_for_the_completed_render(window,tmp_path,monkeypatch,render_format,note_format):
    source=tmp_path/'source.mp4'
    run_ffmpeg(['-f','lavfi','-i','color=size=96x54:rate=24:duration=0.5','-an','-c:v','mpeg4',str(source)])
    media=prepare_media(source)
    window.doc.media={media['id']:media}
    window.doc.state=State((Segment(media['id'],0,12),),position=4,selection=(3,6),frame_markers=(0,8))
    window.doc.rename_marker(8,'Timing')
    window.doc.set_marker_note(8,4,'Check',((0,5,2),))
    folder=tmp_path/'renders'
    folder.mkdir()
    output=folder/('shot.v2.'+render_format)
    destination=tmp_path/'reviews' if note_format=='otio' else folder
    destination.mkdir(exist_ok=True)
    sidecar=destination/output.with_suffix('.'+note_format).name
    seen=[]
    def offer(parent,title,question,buttons,default):
        seen.append(('question',question,output.is_file()))
        window.doc.state=replace(window.doc.state,frame_markers=(),marker_names=(),marker_notes=(),marker_styles=())
        return QMessageBox.Yes
    monkeypatch.setattr(QMessageBox,'question',offer)
    original_exec=CommentExportDialog.exec
    def choose(dialog):
        editor=dialog.findChild(QLineEdit,'fileNameEdit')
        seen.append(('suggestion',Path(dialog.directory().absolutePath()),editor.text()))
        if note_format=='otio':
            label=next(label for label,ext in dialog.formats.items() if ext=='otio')
            dialog.selectNameFilter(label)
            dialog.filterSelected.emit(label)
            dialog.setDirectory(str(destination))
            editor.setText(sidecar.name)
        seen.append(('resolved',Path(dialog.selectedFiles()[0])))
        QTimer.singleShot(25,dialog.accept)
        return original_exec(dialog)
    monkeypatch.setattr(CommentExportDialog,'exec',choose)
    errors=[]
    monkeypatch.setattr(window,'error',errors.append)
    monkeypatch.setattr(window,'export_done',lambda path:seen.append(('done',path)))
    window.start_export(str(output))
    deadline=time.monotonic()+30
    while window.job is not None and time.monotonic()<deadline:
        QTest.qWait(15)
        time.sleep(.002)
    assert window.job is None and not errors
    assert seen==[('question',tr('Enregistrer aussi les marqueurs ?'),True),
                  ('suggestion',folder,'shot.v2.csv'),('resolved',sidecar),('done',str(output))]
    with av.open(str(output)) as container:
        if render_format=='wav':
            assert sum(frame.samples for frame in container.decode(audio=0))==24000
        else:
            assert sum(1 for frame in container.decode(video=0))==12
    if note_format=='csv':
        flavor,raw=load_csv(sidecar)
        rows=map_rows(flavor,raw,24,12)
    else:
        track=json.loads(sidecar.read_bytes())['tracks']['children'][0]
        assert track['kind']==('Audio' if render_format=='wav' else 'Video')
        assert track['children'][0]['media_references']['DEFAULT_MEDIA']['target_url']==output.as_uri()
        assert list(tmp_path.rglob('*.otio'))==[sidecar]
        rows=read_otio(sidecar,24,12)
    assert rows==[ReviewRow(0,1,'',''),ReviewRow(8,4,'Timing','Check',((0,5,2),))]


def test_offer_can_be_declined_or_cancelled_without_touching_existing_files(window,tmp_path,monkeypatch):
    media=tmp_path/'keep.mp4'
    media.write_bytes(b'media')
    sidecar=tmp_path/'keep.csv'
    sidecar.write_bytes(b'prior notes')
    state=window.doc.state
    marked=replace(state,frame_markers=(1,))
    calls=[]
    def question(*_):
        calls.append('question')
        return QMessageBox.Yes if len(calls)>1 else QMessageBox.No
    monkeypatch.setattr(QMessageBox,'question',question)
    def cancel(dialog):
        calls.append('chooser')
        dialog.reject()
        return dialog.result()
    monkeypatch.setattr(CommentExportDialog,'exec',cancel)
    for snapshot in (state,marked,marked):
        offer_rendered_markers(window,media,snapshot,24)
    assert calls==['question','question','chooser']
    assert media.read_bytes()==b'media' and sidecar.read_bytes()==b'prior notes'


def test_marker_write_failure_keeps_the_completed_media(window,tmp_path,monkeypatch):
    media=tmp_path/'approved.wav'
    media.write_bytes(b'completed render')
    errors=[]
    monkeypatch.setattr(window,'error',errors.append)
    monkeypatch.setattr(QMessageBox,'question',lambda *_:QMessageBox.Yes)
    missing=tmp_path/'folder that no longer exists'/'notes.csv'
    monkeypatch.setattr(CommentExportDialog,'destination',lambda *_:(missing,media))
    offer_rendered_markers(window,media,replace(window.doc.state,frame_markers=(2,)),24)
    assert len(errors)==1 and tr('Le média a été exporté. L’enregistrement des marqueurs a échoué.') in errors[0]
    assert media.read_bytes()==b'completed render' and not missing.exists()


@pytest.mark.parametrize('cancel',[False,True])
def test_failed_or_interrupted_render_does_not_offer_markers(window,tmp_path,monkeypatch,cancel):
    from media import Cancelled

    output=tmp_path/('shot.mp4' if cancel else 'invalid.format')
    window.doc.state=replace(window.doc.state,frame_markers=(0,))
    offers=[]
    errors=[]
    monkeypatch.setattr(QMessageBox,'question',lambda *_:offers.append(True))
    monkeypatch.setattr(window,'error',errors.append)
    monkeypatch.setattr(window,'export_done',lambda _:offers.append(True))
    if cancel:
        def wait_for_cancel(state,media,fps,path,apply_exposure,progress,cancel_event,*args,**kwargs):
            if cancel_event.wait(5): raise Cancelled()
            raise AssertionError('Cancellation was not delivered')
        monkeypatch.setattr('app.export_video',wait_for_cancel)
    window.start_export(str(output))
    if cancel: window.job.cancel.set()
    deadline=time.monotonic()+10
    while window.job is not None and time.monotonic()<deadline:
        QTest.qWait(15)
        time.sleep(.002)
    assert window.job is None and not offers and not output.exists()
    assert len(errors)==(0 if cancel else 1)
