# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
import pytest
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from model import Segment
from test_drawing import application
from timeline_skin import card
from widgets import Timeline


@pytest.mark.parametrize('expanded', [False, True])
@pytest.mark.parametrize('left,reverse', [(True, False), (False, False), (True, True), (False, True)])
def test_trim_keeps_decoded_thumbnails_until_replacement_is_ready(application, monkeypatch, expanded, left, reverse):
    widget = Timeline()
    widget.fps = 24
    widget.simple = False
    clip = Segment('test', 12, 44, reversed=reverse)
    meta = dict(proxy='sample.mov', name='sample', fps=24)
    original = []
    for i in range(7 if expanded else 1):
        image = QImage(24, 18, QImage.Format.Format_RGB32)
        image.fill(QColor(230, i * 14, 30))
        original.append(image)
    stage = 'waiting'
    reads = []

    def decoded(media, segment, strip):
        reads.append(segment)
        if segment == clip:
            return tuple(original)
        if stage == 'waiting':
            return ()
        fresh = QImage(24, 18, QImage.Format.Format_RGB32)
        fresh.fill(QColor(30, 210, 40))
        return (fresh,) * (7 if stage == 'complete' and strip else 1)

    def paint(segment, width):
        target = QImage(160, 52, QImage.Format.Format_RGB32)
        target.fill(Qt.black)
        painter = QPainter(target)
        card(painter, widget, QRectF(0, 0, width, 50), segment, meta, False, False, expanded)
        painter.end()
        return target.pixelColor(11, 13), target.pixelColor(round(width / 2), 40)

    monkeypatch.setattr(widget.thumbnails, 'read_segment', decoded)
    assert paint(clip, 150)[0].red() == 230
    widget.clip_trim.preview_track = object()
    for n, width in [(2, 130), (6, 68), (10, 60), (16, 30), (12, 54)]:
        trimmed = clip.sliced(n, clip.length) if left else clip.sliced(0, clip.length - n)
        head, strip = paint(trimmed, width)
        assert head.red() == 230 and (not expanded or strip.red() == 230)
    assert reads == [clip]
    widget.clip_trim.preview_track = None
    assert paint(trimmed, 54)[0].red() == 230
    stage = 'head'
    head, strip = paint(trimmed, 54)
    assert head.green() == 210 and (not expanded or strip.red() == 230)
    stage = 'complete'
    head, strip = paint(trimmed, 54)
    assert head.green() == 210 and (not expanded or strip.green() == 210)
    stage = 'waiting'
    other = widget.thumbnails.get(dict(meta, proxy='other.mov'), replace(trimmed, media='other'), resizing=True)
    assert not other
