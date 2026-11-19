# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from drawing import DrawingKey, Mark
from model import Document, locate
from playlist_store import PlaylistStore


def check(window, output, media):
    window.request_frame = type(window).request_frame.__get__(window)
    def wait(predicate):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if predicate(): return
            time.sleep(.01)
        raise AssertionError('1.18 smoke timed out')
    doc = Document(); doc.append_media([media]); first = doc.active_track_id
    doc.add_media_track(); second = doc.active_track_id; doc.append_media([media])
    doc.select_track(first, extend=True)
    original = doc.state
    assert doc.transfer_media(first, second, 0, 12, 0)
    assert doc.state.tracks[0].length == original.tracks[0].length - 12
    assert all(segment.media is not None for segment in doc.state.tracks[0].segments)
    assert doc.undo() and doc.state == original
    doc.state = replace(doc.state, drawings=(DrawingKey(0, 12, (Mark('brush', ((.3, .3, 1.), (.5, .4, 1.))),)),))
    window.install_doc(doc); window.seek(0); wait(lambda: window.display_frame == 0)
    drawing = window.drawing
    drawing.choose_tool('translate'); drawing.selection.begin((.8, .8), 'translate')
    drawing.selection.move((.9, .9)); drawing.finish()
    assert abs(doc.state.drawings[0].marks[0].points[0][0] - .4) < 1e-6
    assert doc.undo() and abs(doc.state.drawings[0].marks[0].points[0][0] - .3) < 1e-6
    window.video_mirror_action.trigger(); QApplication.processEvents()
    mirror = window.video_mirror
    assert mirror.isVisible() and not mirror.canvas.grab().isNull()
    mirror.on_top.setChecked(True); mirror.opacity.setValue(60)
    assert mirror.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert abs(mirror.windowOpacity() - .6) < .01
    mirror.grab().save(str(output / 'video-mirror.png')); mirror.close()
    assert not window.video_mirror_action.isChecked()
    panel = window.playlists_panel
    identity = panel.store.create('1.18 smoke playlist', [media['path']])
    assert PlaylistStore(panel.store.path).entry(identity)['files'] == [media['path']]
    panel.rebuild((identity, None)); panel.open_current(); wait(lambda: window.job is None)
    assert window.doc is not doc and len(panel.temporary) == 1 and panel.temporary[0]['doc'] is doc
    assert window.doc.media[locate(window.doc.state.segments, 0)[0]]['path'] == media['path']
    panel.current = ('temporary', panel.temporary[0]['id']); panel.open_current()
    assert window.doc is doc and doc.state.second_track is not None and doc.state.drawings
    window.library.show(); window.library_tabs.setCurrentWidget(panel); QApplication.processEvents()
    window.grab().save(str(output / 'playlist-library.png'))
    panel.temporary.clear()
    return dict(playlist_library=True, temporary_full_montage=True, whole_key_translation=True,
                independent_video_window=True, cross_track_no_source_gap=True)
