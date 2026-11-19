# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from pathlib import Path
import threading

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from drawing import DrawingKey, Mark
from model import Segment, locate
from playlist_store import PlaylistStore, scan_folder, copy_into_folder
from test_render1170 import application, clips, document
from test_sync1120 import pump


def test_folder_scan_exclusions_refresh_order_and_persistence(tmp_path):
    folder = tmp_path / 'médias'; folder.mkdir()
    child = folder / 'séquence'; child.mkdir()
    for name in ('a.mp4', 'b.MOV', 'readme.txt'): (folder / name).write_bytes(b'data')
    (child / 'c.mp4').write_bytes(b'data')
    store = PlaylistStore(tmp_path / 'lists.json')
    identity = store.create('Travail', root=folder)
    directories, files = scan_folder(folder)
    assert directories == [str(child)] and len(files) == 2
    store.scanned(identity, folder, files)
    store.set_files(identity, list(reversed(files)), folder)
    store.scanned(identity, folder, files)
    assert store.files(identity, folder) == list(reversed(files))
    store.set_files(identity, [files[1]], folder, [files[0]])
    assert Path(files[0]).exists()
    store.scanned(identity, folder, files)
    assert store.files(identity, folder) == [files[1]]
    (folder / 'd.webm').write_bytes(b'new')
    directories, files = scan_folder(folder)
    store.scanned(identity, folder, files, refresh=True)
    assert len(store.files(identity, folder)) == 3
    reopened = PlaylistStore(store.path)
    assert reopened.entries == store.entries
    reopened.rename(identity, 'Travail renommé'); reopened.remove(identity)
    assert not reopened.entries and all(Path(p).exists() for p in files)


def test_copy_keeps_original_and_collision_and_cancel_rolls_back(tmp_path):
    from media import Cancelled
    source = tmp_path / 'test.mp4'; source.write_bytes(b'a' * 5000000)
    folder = tmp_path / 'destination'; folder.mkdir(); (folder / source.name).write_bytes(b'keep')
    paths = copy_into_folder([source], folder, lambda *args: None, threading.Event())
    assert Path(paths[0]).name == 'test (2).mp4' and Path(paths[0]).read_bytes() == source.read_bytes()
    assert (folder / source.name).read_bytes() == b'keep'
    cancel = threading.Event()
    with pytest.raises(Cancelled):
        copy_into_folder([source, source], folder, lambda *args: cancel.set(), cancel)
    assert sorted(p.name for p in folder.iterdir()) == ['test (2).mp4', 'test.mp4']
    assert source.exists()


def test_failed_save_preserves_library(tmp_path, monkeypatch):
    store = PlaylistStore(tmp_path / 'lists.json'); identity = store.create('Original')
    def denied(*args): raise PermissionError('read only')
    monkeypatch.setattr(Path, 'replace', denied)
    with pytest.raises(PermissionError): store.rename(identity, 'Changed')
    assert store.entry(identity)['name'] == 'Original'
    assert PlaylistStore(store.path).entry(identity)['name'] == 'Original'


def test_open_list_archives_complete_montage_and_restores(application, clips, tmp_path, monkeypatch):
    from app import MainWindow
    monkeypatch.setenv('CADENCE_PREFS', str(tmp_path / 'prefs.json'))
    monkeypatch.setenv('CADENCE_CACHE', str(tmp_path / 'cache'))
    window = MainWindow(); panel = window.playlists_panel
    errors = []; window.error = errors.append
    old = document(clips)
    key = DrawingKey(0, 20, (Mark('brush', ((.2, .3, 1.),)),))
    old.state = replace(old.state, drawings=(key,), frame_markers=(10,))
    old.enable_track_audio(old.state.track_info.id, False)
    window.install_doc(old)
    state = old.state; undo = list(old.undo_stack)
    identity = panel.store.create('Review', [clips[1]['path'], clips[0]['path']])
    panel.rebuild((identity, None))
    try:
        panel.open_current()
        pump(application, lambda: window.job is None, timeout=30)
        assert not errors
        assert len(panel.temporary) == 1 and panel.temporary[0]['doc'] is old
        assert window.doc.state.second_track is None
        assert window.doc.state.length == 96
        assert window.doc.media[locate(window.doc.state.segments, 0)[0]]['path'] == clips[1]['path']
        assert window.doc.media[locate(window.doc.state.segments, 48)[0]]['path'] == clips[0]['path']
        panel.current = ('temporary', panel.temporary[0]['id']); panel.open_current()
        assert window.doc is old and old.state == state and old.undo_stack == undo
        assert len(panel.temporary) == 1
        panel.current = (identity, None); panel.store.set_files(identity, [tmp_path / 'missing.mp4'])
        panel.open_current()
        assert window.doc is old and errors and not window.job
    finally:
        panel.temporary.clear(); window.doc.saved_signature = window.doc.signature(); window.close()
        application.processEvents()


def test_recycle_action_requires_confirmation_and_remove_keeps_file(application, tmp_path, monkeypatch):
    from app import MainWindow
    import playlist_ui
    monkeypatch.setenv('CADENCE_PREFS', str(tmp_path / 'prefs.json'))
    path = tmp_path / 'video.mp4'; path.write_bytes(b'original')
    window = MainWindow(); panel = window.playlists_panel
    identity = panel.store.create('List', [path]); panel.rebuild((identity, None))
    moved = []
    monkeypatch.setattr(playlist_ui.QFile, 'moveToTrash', lambda value: (moved.append(value) is None, ''))
    try:
        panel.files.item(0).setSelected(True)
        monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Cancel)
        panel.trash_files(); assert not moved and panel.files.count() == 1
        panel.remove_files(); assert path.exists() and panel.files.count() == 0
        panel.add_paths([str(path)]); panel.files.item(0).setSelected(True)
        monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
        panel.trash_files(); assert moved == [str(path)] and panel.files.count() == 0
    finally:
        window.close(); application.processEvents()


def test_delete_in_library_preserves_timeline(application, clips, tmp_path, monkeypatch):
    from app import MainWindow
    from PySide6.QtTest import QTest
    monkeypatch.setenv('CADENCE_PREFS', str(tmp_path / 'prefs.json'))
    window = MainWindow(); window.show(); panel = window.playlists_panel
    window.install_doc(document(clips)); before = window.doc.state
    identity = panel.store.create('Delete test', [clips[0]['path']]); panel.rebuild((identity, None))
    window.library.show(); window.library_tabs.setCurrentWidget(panel)
    try:
        panel.files.setFocus(); panel.files.item(0).setSelected(True); application.processEvents()
        QTest.keyClick(panel.files, Qt.Key.Key_Delete)
        assert not panel.store.files(identity) and window.doc.state == before
        assert Path(clips[0]['path']).exists()
    finally:
        window.doc.saved_signature = window.doc.signature(); window.close(); application.processEvents()
