# SPDX-License-Identifier: GPL-3.0-only
from pathlib import Path
import shutil
import time

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


def check(window, output, media):
    w=window; panel=w.playlists_panel; previous=w.doc
    chosen=output/'selected-video.mp4'
    shutil.copyfile(media['path'],chosen)
    identity=panel.store.create('Clips', [media['path'],str(chosen)])
    panel.rebuild((identity,None))
    w.library.show(); w.library_tabs.setCurrentWidget(panel); QApplication.processEvents()
    point=panel.files.visualItemRect(panel.files.item(1)).center()
    QTest.mouseClick(panel.files.viewport(),Qt.LeftButton,Qt.NoModifier,point)
    assert w.doc is previous and w.job is None and panel.files.selectedItems()==[panel.files.item(1)]
    QTest.mouseDClick(panel.files.viewport(),Qt.LeftButton,Qt.NoModifier,point)
    QTest.mouseRelease(panel.files.viewport(),Qt.LeftButton,Qt.NoModifier,point)
    deadline=time.monotonic()+30
    while time.monotonic()<deadline and (w.job or not w.transport.running):
        QTest.qWait(20)
    assert w.job is None and w.transport.running and w.doc is not previous
    assert [Path(m['path']) for m in w.doc.media.values()]==[chosen]
    assert any(record['doc'] is previous for record in panel.temporary)
    assert panel.current==(identity,None) and panel.files.count()==2
    w.pause()
    for width,height in ((1360,890),(640,400)):
        w.resize(width,height); QTest.qWait(100)
        assert panel.tree.mapToGlobal(panel.tree.rect().bottomLeft()).y()<panel.files.mapToGlobal(panel.files.rect().topLeft()).y()
        assert panel.files.parentWidget().rect().contains(panel.files.geometry())
        w.grab().save(str(output/f'library-double-click-{width}.png'))
    w.resize(1360,890)
    w.set_reference_sequence([next(iter(w.doc.media.values()))])
    w.library.show()
    from library_style import LibraryTabs
    bar=w.library_tabs.tabBar()
    assert isinstance(bar,LibraryTabs)
    for index,name in enumerate(('playback','media','library','references')):
        w.library_tabs.setCurrentIndex(index); QTest.qWait(50)
        assert w.library_tabs.tabToolTip(index)==w.library_tabs.tabText(index)
        if bar.compact:
            assert bar.tabRect(index).width()>=bar.fontMetrics().horizontalAdvance(bar.tabText(index))+20
        w.library_tabs.grab().save(str(output/f'panel-{name}.png'))
    return dict(library_single_click_selects=True, library_double_click_autoplay=True, only_chosen_video_opened=True,
                previous_edit_preserved=True)
