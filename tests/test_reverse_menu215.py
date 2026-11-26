# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint

from model import Segment, locate
from test_drawing import application, window


@pytest.mark.parametrize('mode', ['read', 'edit'])
def test_context_menu_reverses_only_clicked_occurrence(window, application, mode):
    w=window
    w.request_frame=lambda: None
    w.workspaces.switch(mode)
    w.doc.state=replace(w.doc.state,segments=(Segment('a',0,10),Segment('a',10,20),
                                              Segment(None,0,10)),selection=(3,17))
    w.refresh()
    application.processEvents()
    t=w.timeline
    y=round(t.simple_track_rect().center().y()) if t.simple else t.track_y('video')+10

    def action_at(frame):
        menu=t.context_menu(QPoint(round(t.x_for(frame+.25)),y))
        try:
            action=next((item for item in menu.actions() if item.data()=='reverse_clip'),None)
            if action:
                checked=action.isChecked()
                action.trigger()
                return checked
        finally:
            menu.deleteLater()

    assert action_at(15) is False
    assert [locate(w.doc.state.segments,f) for f in (0,9,10,19)]==[('a',0),('a',9),('a',19),('a',10)]
    assert w.doc.state.selection==(3,17)
    assert action_at(15) is True
    assert locate(w.doc.state.segments,10)==('a',10)
    assert action_at(25) is None
