# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint

from test_drawing import application, window
from test_studio200 import finish_hide
from timeline_skin import marker_areas


def read_layout(w, app, simple):
    w.resize(760, 530)
    w.move(5, 5)
    w.workspaces.switch('read')
    w.workspaces.set_timeline_simple(simple)
    w.set_panel('transport', True)
    app.processEvents()
    headers = w.studio.headers
    away = w.viewer.mapToGlobal(w.viewer.rect().center())
    headers.update_hover(away)
    finish_hide(w.studio.timeline_bar)
    return headers


@pytest.mark.parametrize('simple', [True, False])
def test_frame_highlight_spans_both_separators(window, application, simple):
    w = window
    headers = read_layout(w, application, simple)
    _, bar = headers.geometries()
    transport = headers.transport_rect()
    timeline = w.timeline
    track_top = timeline.mapToGlobal(QPoint()).y()
    assert bar.bottom() + 1 < transport.top() and transport.bottom() + 1 < track_top
    for y in range(bar.bottom(), track_top):
        x = round(timeline.x_for((y % 13) + 8.5))
        global_x = timeline.mapToGlobal(QPoint(x, 0)).x()
        headers.update_hover(QPoint(global_x, y))
        assert timeline.hover_frame() == timeline.frame_for(x), (x, y, bar, transport, track_top)
    assert w.doc.state.position == 0
    headers.update_hover(w.viewer.mapToGlobal(w.viewer.rect().center()))
    assert timeline.transport_hover_x is None


def test_hover_comment_has_priority_over_lower_bars(window, application):
    w = window
    headers = read_layout(w, application, True)
    text = '\n'.join(['Vérifier la pose de contact et la silhouette.'] * 17)
    w.doc.state = replace(w.doc.state, frame_markers=(6,), marker_notes=((6, 1, text),))
    w.refresh()
    t = w.timeline
    marker = next(marker_areas(t))[2].center()
    t.marker_hover.hover((6, ''), marker)
    t.marker_hover.show_note()
    popup = t.marker_hover.popup
    assert popup.isVisible()
    _, bar = headers.geometries()
    for strip in (bar, headers.transport_rect()):
        overlap = strip.intersected(popup.frameGeometry())
        assert not overlap.isEmpty()
        headers.update_hover(overlap.center())
        finish_hide(w.studio.timeline_bar)
        assert not w.studio.timeline_bar.isVisible()
        assert t.transport_hover_x is None
    popup.hide()
    headers.update_hover(overlap.center())
    assert w.studio.timeline_bar.isVisible()
