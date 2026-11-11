# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
import numpy as np
import pytest
from PySide6.QtCore import Qt,QPointF
from PySide6.QtGui import QImage,QPainter,QTransform
from drawing import DrawingKey,Mark
from test_drawing import application,window


def render(viewer,dpr):
    image=QImage(round(viewer.width()*dpr),round(viewer.height()*dpr),QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr);image.fill(Qt.GlobalColor.transparent)
    painter=QPainter(image)
    try: viewer.paint_scene(painter)
    finally: painter.end()
    return image


def display_point(viewer,x,y):
    size=viewer.image.size().scaled(viewer.size(),Qt.AspectRatioMode.KeepAspectRatio)
    transform=QTransform();transform.translate(viewer.width()/2+viewer.pan.x(),viewer.height()/2+viewer.pan.y());transform.rotate(viewer.angle);transform.scale(viewer.zoom,viewer.zoom)
    return transform.map(QPointF((x-.5)*size.width(),(y-.5)*size.height()))


@pytest.mark.parametrize('swapped',[False,True])
def test_wipe_clips_current_key_and_onion_to_working_video(window,swapped):
    w=window;v=w.viewer;w.request_frame=lambda:None
    def stroke(y): return Mark(points=((.05,y,1),(.95,y,1)),size=.08,color='#ffffff',pressure=False)
    w.doc.state=replace(w.doc.state,position=10,drawings=(DrawingKey(8,9,(stroke(.3),)),DrawingKey(10,11,(stroke(.5),)),DrawingKey(12,13,(stroke(.7),))))
    w.drawing.visible.setChecked(True);w.drawing.onion.setChecked(True);w.drawing.before.setValue(3);w.drawing.after.setValue(3);w.drawing.ghost.setValue(100)
    v.comparing=True;v.compare_mode='wipe';v.compare_swapped=swapped
    v.reference_rgb=np.full((360,640,3),[20,40,80],dtype=np.uint8);v.set_frame(np.full((360,640,3),[40,70,90],dtype=np.uint8))
    for angle,zoom,dpr in ((0,1,1),(27,.8,1),(-20,.8,2)):
        v.angle=angle;v.zoom=zoom;v.pan=QPointF(3,4)
        for split in (0,.2,.5,.8,1):
            v.wipe_position=split;image=render(v,dpr)
            for x in (.1,.4,.6,.9):
                work=(x>split) if swapped else (x<split)
                for y in (.3,.5,.7):
                    point=display_point(v,x,y);color=image.pixelColor(round(point.x()*dpr),round(point.y()*dpr))
                    if work: assert color.red()>100,(swapped,split,x,y,color.getRgb())
                    else: assert color.getRgb()[:3]==(20,40,80),(swapped,split,x,y,color.getRgb())
                point=display_point(v,x,.5)
                assert (w.drawing.point(point) is not None)==work
                assert w.drawing.point(point,True)==pytest.approx((x,.5))
    v.comparing=False;v.apply_effect();image=render(v,1)
    for x in (.1,.9):
        point=display_point(v,x,.5);assert image.pixelColor(round(point.x()),round(point.y())).red()>240


def test_wipe_clips_in_progress_drawing_and_keeps_handle_in_front(window):
    w=window;v=w.viewer;v.comparing=True;v.compare_mode='wipe';v.wipe_position=.5
    v.reference_rgb=np.zeros((360,640,3),dtype=np.uint8);v.set_frame(v.reference_rgb.copy())
    w.drawing.visible.setChecked(True);w.drawing.stroke_key=DrawingKey(0,1,())
    w.drawing.stroke=Mark(points=((.1,.5,1),(.9,.5,1)),size=.15,color='#ff0000',pressure=False)
    image=render(v,1)
    a=display_point(v,.25,.5);b=display_point(v,.75,.5);center=display_point(v,.5,.5)
    assert image.pixelColor(round(a.x()),round(a.y())).red()>240
    assert image.pixelColor(round(b.x()),round(b.y())).red()==0
    assert image.pixelColor(round(center.x()),round(center.y())).green()>180
    w.drawing.stroke=None


def test_wipe_handle_has_smooth_alpha_at_display_resolution(window):
    v=window.viewer
    image=QImage(40,40,QImage.Format.Format_ARGB32_Premultiplied);image.fill(Qt.GlobalColor.transparent)
    painter=QPainter(image);painter.translate(20,20)
    try: v.paint_wipe_handle(painter,0)
    finally: painter.end()
    alpha=np.frombuffer(image.bits(),np.uint8).reshape(40,image.bytesPerLine())[:,3::4]
    assert np.count_nonzero((alpha>0)&(alpha<255))>20
