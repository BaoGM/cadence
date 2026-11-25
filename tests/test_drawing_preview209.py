# SPDX-License-Identifier: GPL-3.0-only
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QListWidget, QMenu

from test_drawing import application, window


def test_preview_gamma_uses_gpu_lookup_and_leaves_source_intact(window):
    from native_d3d import prepare as direct3d
    from native_gpu import prepare as opengl

    source=np.full((16,32,3),64,dtype=np.uint8)
    window.viewer.set_frame(source)
    initial=window.doc.signature()
    control=window.drawing.gamma
    assert (control.minimum(),control.value(),control.maximum())==(-10,0,10)
    for adjustment, expected in ((-10,0),(-5,32),(5,160),(10,255)):
        control.setValue(adjustment)
        assert window.viewer.cpu_preview().pixelColor(2,2).red()==expected
        for backend in (direct3d,opengl):
            arrays,lookup,_,_,bypass=backend(source,gamma=window.viewer.preview_gamma)
            assert arrays[0] is source and not bypass
            assert tuple(lookup[64])==(expected,expected,expected,255)
    control.setValue(0)
    assert window.viewer.cpu_preview().pixelColor(2,2).red()==64
    assert np.all(source==64) and window.doc.signature()==initial


def test_volume_arrows_yield_to_list_and_numeric_navigation(window,application):
    window.activateWindow()
    window.viewer.setFocus()
    application.processEvents()
    window.volume.setValue(50)
    window.volume.setMuted(True)
    QTest.keyClick(window.viewer,Qt.Key_Up)
    assert window.volume.value()==55 and not window.volume.muted
    QTest.keyClick(window.viewer,Qt.Key_Down)
    assert window.volume.value()==50
    window.timeline.setFocus()
    QTest.keyClick(window.timeline,Qt.Key_Down)
    assert window.volume.value()==45
    QTest.keyClick(window.timeline,Qt.Key_Up)

    rows=QListWidget(window.library)
    rows.addItems(['A','B'])
    rows.show(); rows.setFocus(); rows.setCurrentRow(0)
    QTest.keyClick(rows,Qt.Key_Down)
    assert rows.currentRow()==1 and window.volume.value()==50
    size=window.drawing.size
    size.setFocus()
    value=size.value()
    QTest.keyClick(size,Qt.Key_Up)
    assert size.value()==value+size.singleStep() and window.volume.value()==50
    menu=QMenu(window)
    first=menu.addAction('A'); second=menu.addAction('B')
    menu.popup(window.viewer.mapToGlobal(window.viewer.rect().center()))
    menu.setActiveAction(first)
    QTest.keyClick(menu,Qt.Key_Down)
    assert menu.activeAction() is second and window.volume.value()==50
    menu.close()
