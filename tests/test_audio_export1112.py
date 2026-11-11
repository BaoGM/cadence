# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from pathlib import Path
import threading
import wave

import av
import numpy as np
import pytest

import media
from export_dialog import ExportDialog, default_destination, FORMATS
from model import Document, State, Segment, TimelinePCM, RATE, sample_at
from test_drawing import application
from ui_text import tr


@pytest.fixture
def edited_audio(tmp_path, monkeypatch):
    monkeypatch.setenv('CADENCE_CACHE', str(tmp_path/'cache'))
    source = tmp_path/'source.wav'
    media.run_ffmpeg(['-f','lavfi','-i','sine=frequency=440:duration=3','-ar','44100',str(source)])
    item = media.prepare_media(source)
    doc = Document()
    doc.media = {item['id']: item}
    key = item['id']
    doc.state = State((Segment(None,0,54),), audio_segments=(
        Segment(key,24,42), Segment(None,0,6), Segment(key,0,6,muted=True), Segment(key,0,24)))
    return doc


@pytest.mark.parametrize('extension', ['wav','mp3'])
def test_audio_export_edited_timeline(edited_audio, tmp_path, extension):
    doc = edited_audio
    output = tmp_path/f'result.{extension}'
    progress = []
    assert media.export_video(doc.state, dict(doc.media), doc.fps, output,
                              progress=lambda value,message: progress.append(value)) == str(output)
    assert progress[-1] == 1 and progress == sorted(progress)
    with av.open(str(output)) as container:
        assert not container.streams.video and len(container.streams.audio) == 1
        stream = container.streams.audio[0]
        assert stream.sample_rate == RATE and stream.codec_context.channels == 2
        samples = np.concatenate([frame.to_ndarray().reshape(2,-1) for frame in container.decode(audio=0)],axis=1)
    assert samples.shape[1] == sample_at(doc.state.length,doc.fps)
    if extension == 'wav':
        pcm = TimelinePCM(doc.state.audio,doc.media,doc.fps)
        try: expected = pcm.read(0,pcm.samples)
        finally: pcm.close()
        with wave.open(str(output),'rb') as audio:
            assert audio.getsampwidth() == 2 and audio.getframerate() == RATE
            assert audio.readframes(audio.getnframes()) == expected
    else:
        assert np.abs(samples[:,:RATE//2]).max() > .02
        assert np.abs(samples[:,RATE:RATE+RATE//8]).max() < .001
    assert not list(tmp_path.glob('*.partial.*'))


def test_audio_export_missing_video_and_cancel(edited_audio,tmp_path):
    doc = edited_audio
    doc.media['video'] = {'path': str(tmp_path/'missing.mp4')}
    state = replace(doc.state,segments=(Segment('video',0,doc.state.length),))
    output = tmp_path/'audio.wav'
    media.export_video(state,dict(doc.media),doc.fps,output)
    original = output.read_bytes()
    cancel = threading.Event()
    with pytest.raises(media.Cancelled):
        media.export_video(state,dict(doc.media),doc.fps,output,cancel=cancel,
                           progress=lambda value,message: cancel.set() if message=='Encodage audio' else None)
    assert output.read_bytes() == original and not list(tmp_path.glob('*.partial.*'))


def test_audio_export_source_and_permission_protection(edited_audio,tmp_path,monkeypatch):
    doc = edited_audio
    source = Path(next(iter(doc.media.values()))['path'])
    original = source.read_bytes()
    with pytest.raises(ValueError,match='média source'):
        media.export_video(doc.state,dict(doc.media),doc.fps,source)
    assert source.read_bytes() == original
    def denied(**kwargs):
        raise PermissionError('denied')
    monkeypatch.setattr(media.tempfile,'TemporaryFile',denied)
    monkeypatch.setattr(media,'validate_media',lambda *_: pytest.fail('Preparation before checking destination'))
    with pytest.raises(ValueError,match='dossier est protégé'):
        media.export_video(doc.state,dict(doc.media),doc.fps,tmp_path/'protected.wav')


def test_export_destination_and_filters(edited_audio,tmp_path,application,monkeypatch):
    from PySide6.QtWidgets import QComboBox,QLineEdit,QFileDialog
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from file_dialogs import install_file_places
    install_file_places()
    doc = edited_audio
    cwd = tmp_path/'installation'; cwd.mkdir(); monkeypatch.chdir(cwd)
    assert default_destination(doc) == tmp_path/'source-montage.wav'
    project_folder = tmp_path/'projects'; project_folder.mkdir()
    doc.project_path = str(project_folder/'Cut.cadence')
    assert default_destination(doc) == project_folder/'Cut-montage.wav'
    for language in ('fr','en'):
        import ui_text
        monkeypatch.setattr(ui_text,'_language',language)
        dialog = ExportDialog(None,doc)
        try:
            dialog.show(); application.processEvents()
            assert Path(dialog.selectedFiles()[0]) == default_destination(doc)
            labels=('Dossier :','Nom de fichier :','Type de fichier :') if language=='fr' else ('Look in:','File name:','File type:')
            for role,label in zip((QFileDialog.DialogLabel.LookIn,QFileDialog.DialogLabel.FileName,QFileDialog.DialogLabel.FileType),labels):
                assert dialog.labelText(role).replace('&','')==label
            field=dialog.findChild(QLineEdit,'fileNameEdit')
            combo=dialog.findChild(QComboBox,'fileTypeCombo')
            for extension,label in FORMATS.items():
                index=combo.findText(tr(label)); assert index>=0
                QTest.keyClick(combo,Qt.Key.Key_Home)
                for _ in range(index): QTest.keyClick(combo,Qt.Key.Key_Down)
                application.processEvents()
                assert Path(dialog.selectedFiles()[0]) == project_folder/('Cut-montage'+extension)
                assert dialog.defaultSuffix() == extension[1:]
                assert field.text()=='Cut-montage'+extension
            field.clear(); QTest.keyClick(combo,Qt.Key.Key_Home); application.processEvents()
            assert not field.text() and Path(dialog.directory().absolutePath())==project_folder
            target=tmp_path/'exports é'; target.mkdir(exist_ok=True)
            field.setText(str(target/'renamed.mp3'))
            index=combo.findText(tr(FORMATS['.wav']))
            QTest.keyClick(combo,Qt.Key.Key_Home)
            for _ in range(index): QTest.keyClick(combo,Qt.Key.Key_Down)
            application.processEvents()
            assert field.text()=='renamed.wav'
            assert Path(dialog.selectedFiles()[0])==target/'renamed.wav'
        finally: dialog.close(); dialog.deleteLater()
        folder_dialog=QFileDialog(None,directory=str(tmp_path))
        folder_dialog.setFileMode(QFileDialog.FileMode.Directory)
        folder_dialog.show(); application.processEvents()
        try:
            assert folder_dialog.labelText(QFileDialog.DialogLabel.FileName).replace('&','')==('Nom de dossier :' if language=='fr' else 'Folder name:')
        finally: folder_dialog.close(); folder_dialog.deleteLater()


def test_destination_falls_back_from_protected_project(edited_audio,tmp_path,monkeypatch):
    import export_dialog
    doc = edited_audio
    protected = tmp_path/'Program Files'; protected.mkdir()
    doc.project_path = str(protected/'Saved.cadence')
    original = export_dialog.tempfile.TemporaryFile
    def probe(*args,**kwargs):
        if kwargs.get('dir') == protected: raise PermissionError('denied')
        return original(*args,**kwargs)
    monkeypatch.setattr(export_dialog.tempfile,'TemporaryFile',probe)
    assert default_destination(doc) == tmp_path/'Saved-montage.wav'


def test_audio_export_waits_for_pending_audio(tmp_path,monkeypatch):
    monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache'))
    source=tmp_path/'pending.mp4'
    media.run_ffmpeg(['-f','lavfi','-i','color=c=black:s=160x90:r=25:d=1',
                     '-f','lavfi','-i','sine=frequency=440:duration=1',
                     '-c:v','libx264','-c:a','aac',str(source)])
    item=media.prepare_media(source,defer_audio=True)
    assert item['audio_pending']
    doc=Document(25); doc.append_media([item])
    output=tmp_path/'ready.wav'
    media.export_video(doc.state,dict(doc.media),doc.fps,output)
    with wave.open(str(output),'rb') as audio:
        assert audio.getnframes()==sample_at(doc.state.length,doc.fps)
        assert np.abs(np.frombuffer(audio.readframes(audio.getnframes()),dtype='<i2')).max()>1000
