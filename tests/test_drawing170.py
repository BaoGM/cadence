# SPDX-License-Identifier: GPL-3.0-only
import random
from dataclasses import replace
import numpy as np
import pytest
from PySide6.QtCore import Qt,QRectF,QPoint
from PySide6.QtGui import QImage,QPainter,QColor,QPen
from drawing import Mark,DrawingKey,render_marks,render_layer,active_key,nearby_keys,vector_path,VECTOR_TOOLS
from drawing_cache import DrawingRasterCache
from affine import IDENTITY,compose,pixel
from test_native140 import application


def reference_marks(marks,width,height,outer=IDENTITY):
    from native_render import paint_stroke
    from draw_text import paint_text
    image=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied);image.fill(Qt.GlobalColor.transparent)
    for mark in marks:
        matrix=compose(outer,mark.transform)
        if mark.tool=='group': ink=reference_marks(mark.children,width,height,matrix)
        else:
            ink=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied);ink.fill(Qt.GlobalColor.transparent)
            p=QPainter(ink);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setTransform(pixel(matrix,width,height))
            color=QColor(mark.color);p.setPen(Qt.PenStyle.NoPen);p.setBrush(color)
            if mark.tool=='text': p.setPen(color);paint_text(p,mark,width,height)
            elif mark.tool in VECTOR_TOOLS:
                p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(QPen(color,max(.5,mark.size*height),Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin));p.drawPath(vector_path(mark,width,height))
            else: assert paint_stroke(p,mark,width,height)
            p.end()
        p=QPainter(image);p.setOpacity(mark.opacity)
        if mark.tool=='eraser':p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
        p.drawImage(0,0,ink);p.end()
    return image


@pytest.mark.parametrize('size',[(101,59),(853,480),(3840,2160)])
def test_bounded_ink_preserves_pixels(application,size):
    rng=random.Random(170)
    transforms=[IDENTITY,(.8,.2,-.1,1.2,.03,-.08),(-1,0,0,1,1,0),(1,0,.9,1,-.3,0)]
    for matrix in transforms:
        marks=[]
        for i in range(24):
            x,y=rng.uniform(-.1,.95),rng.uniform(-.1,.95)
            marks.append(Mark(tool=('brush','eraser','rectangle','ellipse','arrow')[i%5],points=((x,y,.1),(x+.1,y+.06,.8)),size=.02,opacity=.62,sensitivity=2.2,transform=matrix,angle=17 if i%5>1 else 0))
        marks.append(Mark(tool='text',points=((.2,.3,1),),text='Cadence',box=(.4,.2),transform=matrix))
        marks.append(Mark(tool='group',points=((0,0,1),),children=tuple(marks[:2]),opacity=.4,transform=matrix))
        expected=reference_marks(marks,*size);actual=render_marks(marks,*size)
        assert actual==expected


def test_native_alpha_bounds_and_empty(application,monkeypatch):
    from native_render import alpha_bounds
    for width in (1,17,1023):
        image=QImage(width,43,QImage.Format.Format_ARGB32_Premultiplied);image.fill(Qt.GlobalColor.transparent)
        assert alpha_bounds(image).isEmpty()
        image.setPixelColor(width-1,42,QColor(255,0,0,1))
        expected=(width-1,42,1,1)
        for native in ('0','1'):
            monkeypatch.setenv('CADENCE_NATIVE_RENDER',native)
            assert alpha_bounds(image).getRect()==expected


def test_sparse_keys_fit_cache_and_match_uncached(application,monkeypatch):
    import drawing
    keys=tuple(DrawingKey(i,i+1,(Mark(points=((.25+i*.005,.5,1),),size=.01),)) for i in range(31))
    cache=DrawingRasterCache(64*1024);original=drawing.render_marks;calls=[]
    def count(*args,**kwargs):calls.append(1);return original(*args,**kwargs)
    monkeypatch.setattr(drawing,'render_marks',count)
    expected=render_layer(keys,15,640,360,15,15,.8)
    assert render_layer(keys,15,640,360,15,15,.8,cache)==expected
    calls.clear();assert render_layer(keys,15,640,360,15,15,.8,cache)==expected
    assert not calls and cache.bytes<=cache.budget and len(cache.entries)==31
    for frame in (16,17,18,19,20):
        assert render_layer(keys,frame,640,360,15,15,1,cache)==render_layer(keys,frame,640,360,15,15,1)
    cache.retain(keys);cache.retain(keys[1:]);assert id(keys[0].marks) not in {key[0] for key in cache.entries}


def test_indexed_keys_match_linear_search():
    keys=tuple(DrawingKey(i*5,i*5+3,()) for i in range(10000))
    for frame in (-1,0,1,2,3,4,49997,50000):
        assert active_key(keys,frame)==next((key for key in keys if key.start<=frame<key.end),None)
        found=tuple(nearby_keys(keys,frame,3,5))
        expected=tuple(key for key in keys if key.end>=frame-3+1 and key.start<=frame+5)
        assert found==expected


def test_timeline_readout_units_and_no_overlap(application,monkeypatch):
    import widgets
    from model import State,Segment
    timeline=widgets.Timeline();timeline.resize(1200,126)
    timeline.set_document(State((Segment('x',0,100000),),position=3600),{},24)
    timeline.hover_x=timeline.x_for(70000)
    records=[];original=widgets.paint_frame_number
    def capture(p,text,*args,**kw):
        rect=original(p,text,*args,**kw);records.append((text,rect));return rect
    monkeypatch.setattr(widgets,'paint_frame_number',capture)
    image=QImage(1200,126,QImage.Format.Format_ARGB32_Premultiplied)
    for simple in (False,True):
        timeline.simple=simple;timeline.hover_x=timeline.x_for(70000)
        for units in ('frames','time'):
            timeline.units=units;records.clear();p=QPainter(image);timeline.paint_frame_indicator(p);p.end()
            assert [r[0] for r in records]==[timeline.tick_label(3600),timeline.tick_label(timeline.frame_for(timeline.hover_x))]
            assert not records[0][1].intersects(records[1][1])
        timeline.hover_x=timeline.x_for(3601);records.clear();p=QPainter(image);timeline.paint_frame_indicator(p);p.end()
        assert len(records)==1


def test_timeline_drawing_cache_follows_edits_not_position(application):
    from model import State,Segment
    from widgets import Timeline
    t=Timeline();t.resize(1200,126)
    key=DrawingKey(0,20,(Mark(points=((.5,.5,1),)),));state=State((Segment('x',0,30000),),drawings=(key,))
    image=QImage(1200,126,QImage.Format.Format_ARGB32_Premultiplied)
    for simple in (False,True):
        t.simple=simple;t.set_document(state,{},24);t.render(image);cached=t.drawing_track.raster[2].cacheKey()
        t.state=replace(state,position=10000,selection=(100,20000));t.render(image)
        assert t.drawing_track.raster[2].cacheKey()==cached
        t.state=replace(state,drawings=(replace(key,end=4000),));t.render(image)
        assert t.drawing_track.raster[2].cacheKey()!=cached


def test_region_compositing_matches_full_onions_and_mirrors(application):
    marks=(Mark(points=((.3,.4,1),(.45,.55,.3)),size=.03,opacity=.7),Mark(tool='eraser',points=((.4,.5,1),),size=.04))
    keys=tuple(DrawingKey(i*3,i*3+2,tuple(replace(m,color=f'#{0x124711+i*9000:06x}') for m in marks)) for i in range(5))
    cache=DrawingRasterCache()
    for frame in range(16):
        expected=QImage(853,480,QImage.Format.Format_ARGB32_Premultiplied);expected.fill(Qt.GlobalColor.transparent)
        p=QPainter(expected)
        current=active_key(keys,frame);others=[]
        for key in keys:
            if key is current:continue
            distance=frame-key.end+1 if key.end<=frame else key.start-frame
            if 1<=distance<=5: others.append((distance,key))
        for distance,key in sorted(others,key=lambda pair:pair[0],reverse=True):
            p.setOpacity(.8*(6-distance)/6);p.drawImage(0,0,reference_marks(key.marks,853,480))
        if current:p.setOpacity(1);p.drawImage(0,0,reference_marks(current.marks,853,480))
        p.end()
        assert render_layer(keys,frame,853,480,5,5,.8,cache)==expected
        origin,image=render_layer(keys,frame,853,480,5,5,.8,cache,region=True)
        for horizontal,vertical in ((False,False),(True,False),(False,True),(True,True)):
            restored=QImage(expected.size(),expected.format());restored.fill(Qt.GlobalColor.transparent)
            x=853-origin[0]-image.width() if horizontal else origin[0];y=480-origin[1]-image.height() if vertical else origin[1]
            p=QPainter(restored);p.drawImage(x,y,image.mirrored(horizontal,vertical));p.end()
            assert restored==expected.mirrored(horizontal,vertical)
