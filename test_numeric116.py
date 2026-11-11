# SPDX-License-Identifier: GPL-3.0-only
import pytest
from PySide6.QtCore import Qt,QPoint,QLocale
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QTabWidget
from test_drawing import application,window


@pytest.mark.parametrize('mode',['horizontal','vertical','overlay','difference','front'])
def test_comparison_values_editable_in_every_mode(window,application,mode):
    w=window; w.request_frame=lambda:None; w.comparison_panel.show()
    w.compare_mode.setCurrentIndex(w.compare_mode.findData(mode)); application.processEvents()
    for spin,text,value in ((w.compare_opacity,'41',41),(w.compare_gain,'2,50',2.5)):
        spin.setLocale(QLocale('fr_FR')); assert spin.isEnabled()
        edit=spin.lineEdit(); QTest.mouseClick(edit,Qt.MouseButton.LeftButton,pos=QPoint(8,edit.height()//2))
        assert edit.hasFocus() and edit.hasSelectedText()
        QTest.keyClicks(edit,text); QTest.keyClick(edit,Qt.Key.Key_Return)
        assert spin.value()==pytest.approx(value)
    w.compare_mode.setCurrentIndex(w.compare_mode.findData('overlay'))
    assert w.viewer.compare_opacity==.41
    w.compare_mode.setCurrentIndex(w.compare_mode.findData('difference'))
    assert w.viewer.compare_gain==2.5


@pytest.mark.parametrize('field,text,value',[
    ('drawing.before','10',10),('drawing.after','12',12),('drawing.ghost','80',80),
    ('drawing.size','14,50',14.5),('drawing.opacity','65',65),('drawing.sensitivity','2,50',2.5),
    ('compare_opacity','75',75),('compare_gain','2,50',2.5),('compare_offset','-10',-10),('exp_spin','1,50',1.5),
])
def test_single_click_replaces_numeric_value_on_enter(window,application,field,text,value):
    w=window; w.request_frame=lambda:None
    w.drawing.choose_tool('brush')
    if field in ('compare_opacity','compare_gain'):
        w.compare_mode.setCurrentIndex(w.compare_mode.findData('overlay' if field=='compare_opacity' else 'difference'))
    w.drawing.panel.show(); w.comparison_panel.show(); w.header.show()
    tabs=w.drawing.panel.findChild(QTabWidget)
    tabs.setCurrentIndex(0)
    spin=w
    for part in field.split('.'): spin=getattr(spin,part)
    spin.setLocale(QLocale('fr_FR')); application.processEvents()
    edit=spin.lineEdit(); original=spin.value()
    QTest.mouseClick(edit,Qt.MouseButton.LeftButton,pos=QPoint(8,edit.height()//2))
    assert edit.hasSelectedText()
    changes=[]; spin.valueChanged.connect(changes.append)
    QTest.keyClicks(edit,text)
    assert spin.value()==original and not changes
    QTest.keyClick(edit,Qt.Key.Key_Return)
    assert spin.value()==pytest.approx(value) and changes==[value]
    if field in ('drawing.before','drawing.after'): assert spin.suffix()==''
    # Clicking again, even with focus already in the field, replaces the whole value.
    QTest.mouseClick(edit,Qt.MouseButton.LeftButton,pos=QPoint(edit.width()-8,edit.height()//2))
    QTest.keyClicks(edit,'2'); QTest.keyClick(edit,Qt.Key.Key_Return)
    assert spin.value()==2
