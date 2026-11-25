# SPDX-License-Identifier: GPL-3.0-only
import math
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from drawing import DrawingKey, Mark
from model import Segment, State
from test_drawing import application, window
from timeline_skin import ruler_ticks
from widgets import Timeline


@pytest.mark.parametrize('simple',[False,True])
def test_clip_toggle_and_inclusive_anchor_across_a_gap(window,simple):
    w=window; t=w.timeline
    w.request_frame=lambda:None
    w.doc.state=State(tuple(Segment(key,0,10,cut_before=True) for key in ('a','a',None,'a','a','a')),position=14)
    w.refresh(); w.workspaces.set_timeline_simple(simple)
    y=round(t.simple_track_rect().center().y()) if simple else t.track_y('video')+8
    def press(frame,modifiers):
        pt=QPoint(round(t.x_for(frame)),y)
        QTest.mouseClick(t,Qt.LeftButton,modifiers,pt)
        QTest.mouseDClick(t,Qt.LeftButton,modifiers,pt)
        QTest.mouseRelease(t,Qt.LeftButton,modifiers,pt)
    press(44,Qt.ControlModifier|Qt.ShiftModifier)
    assert w.doc.state.selection_ranges()==((10,20),(30,40),(40,50))
    press(54,Qt.NoModifier)
    press(34,Qt.ControlModifier)
    assert w.doc.state.selection_ranges()==((30,40),(50,60))
    press(4,Qt.ControlModifier|Qt.ShiftModifier)
    assert w.doc.state.selection_ranges()==((0,10),(10,20),(30,40),(50,60))
    press(34,Qt.ControlModifier)
    assert w.doc.state.selection_ranges()==((0,10),(10,20),(50,60))
    QTest.mouseClick(t,Qt.LeftButton,Qt.ControlModifier,QPoint(round(t.x_for(4)),y))
    assert w.doc.state.selection_ranges()==((0,10),(10,20),(50,60))


def test_simplified_ruler_ticks_stay_inside_separate_clips(application):
    t=Timeline(); t.simple=True; t.resize(970,42)
    t.set_units('frames')
    t.set_document(State((Segment('a',0,37),Segment('b',0,83)),position=2),{},24)
    image=t.grab().toImage(); bar=t.simple_track_rect()
    top,cy,bottom=int(bar.top()),int(bar.center().y()),int(bar.bottom())-1
    assert t.height()==42 and bar.height()==17
    def tone(x,y): return image.pixelColor(x,y).lightness()
    ticks=[(math.floor(t.x_for(f)),major) for f,_,major in ruler_ticks(t) if 4<f<110]
    major=next(x for x,big in ticks if big)
    minor=next(x for x,big in ticks if not big)
    assert all(tone(major,y)<48 for y in range(top,bottom+1))
    assert all(tone(minor,y)<48 for y in range(cy-4,cy+5))
    assert tone(minor,top)>50 and tone(minor,bottom)>50
    assert tone(major,top-3)==tone(major+4,top-3)
    first_gap=math.floor(t.x_for(37)-1)
    assert all(image.pixelColor(x,cy).name()=='#161d25' for x in range(first_gap,first_gap+3))
    for edge in (first_gap-1,first_gap+3):
        assert tone(edge,top)<tone(edge,cy) and tone(edge,bottom)<tone(edge,cy)
    t.deleteLater()


@pytest.mark.parametrize('selected',[False,True])
def test_ticks_leave_rounded_cuts_and_ends_visible(application,selected):
    t=Timeline(); t.simple=True; t.resize(900,42); t.set_units('frames')
    state=State(tuple(Segment('a',0,n,cut_before=True) for n in (50,65,85)),position=171,
                selection=(0,200) if selected else None)
    t.set_document(state,{},24)
    assert t.ruler_steps()==(5,25)
    image=t.grab().toImage()
    bar=t.simple_track_rect(); top=int(bar.top()); bottom=int(bar.bottom())-1; middle=int(bar.center().y())
    base='#161d25'; inside=image.pixelColor(round(t.x_for(11)),middle).name()
    for f in (0,50,115,200):
        x=round(t.x_for(f))
        if 0<f<200:
            first_gap=math.floor(t.x_for(f)-1)
            for column in range(first_gap,first_gap+3):
                assert all(image.pixelColor(column,y).name()==base for y in range(top,bottom+1))
            edges=((first_gap-1,-1),(first_gap+3,1))
        else:
            edges=((x,1),) if f==0 else ((x-1,-1),)
        for edge,sign in edges:
            assert image.pixelColor(edge,middle).name()==inside
            assert image.pixelColor(edge,top).name()==base
            assert image.pixelColor(edge,bottom).name()==base
            assert all(image.pixelColor(edge,y).lightness()>=18 for y in range(top,bottom+1))
            assert image.pixelColor(edge+sign*5,top).name()==inside
            assert image.pixelColor(edge+sign*5,bottom).name()==inside
    for f in (45,55,100,110,120,125):
        x=int(t.x_for(f)+.5)
        background=image.pixelColor(x+4,middle).red()
        coverage=sum(1-image.pixelColor(i,middle).red()/background for i in range(x-2,x+3))
        assert coverage==pytest.approx(2 if f%25==0 else .75,abs=.05)
    t.deleteLater()


def test_zoomed_out_nearby_ticks_are_suppressed_without_false_viewport_corners(application):
    t=Timeline(); t.simple=True; t.resize(640,42); t.set_units('frames')
    t.set_document(State((Segment('a',0,2434),Segment('b',0,2566)),position=30),{},24)
    quantum,major=t.ruler_steps()
    frame=round(2434/quantum)*quantum
    assert abs(t.x_for(frame)-t.x_for(2434))<4
    image=t.grab().toImage(); bar=t.simple_track_rect(); mid=int(bar.center().y())
    for x in range(round(t.x_for(frame))-1,round(t.x_for(frame))+2):
        assert image.pixelColor(x,mid).name()=='#2d4249'
    # Both viewport edges fall inside the first source clip.
    t.zoom=10; t.view_start=121; image=t.grab().toImage()
    for x in (t.track_left(),t.track_right()-1):
        assert image.pixelColor(x,int(bar.top())).name()=='#2d4249'
    t.deleteLater()


def test_one_pixel_clips_remain_visible_between_cuts(application):
    t=Timeline(); t.simple=True; t.resize(640,42); t.set_units('frames')
    count=t.track_right()-t.track_left()
    clips=tuple(Segment(str(i),0,1) for i in range(count))
    t.set_document(State(clips,position=0),{},24)
    image=t.grab().toImage(); middle=int(t.simple_track_rect().center().y())
    for i in range(4,count-4):
        assert image.pixelColor(round(t.x_for(i)),middle).name()=='#2d4249'
    t.deleteLater()


def test_drawing_is_centered_in_detailed_lane(application):
    t=Timeline(); t.resize(800,120)
    key=DrawingKey(7,25,(Mark(points=((.3,.3,1),)),))
    st=State((Segment('a',0,96),),drawings=(key,))
    t.set_document(st,{},24); image=t.grab().toImage()
    x=round(t.x_for(15))
    ys=[y for y in range(t.marker_lane_height,t.ruler_y()) if image.pixelColor(x,y).lightness()>85]
    assert t.drawing_lane_height==17 and len(ys)>=2
    assert abs((min(ys)+max(ys))/2-(t.marker_lane_height+t.ruler_y()-1)/2)<=1
    t.deleteLater()


@pytest.mark.parametrize('simple',[False,True])
@pytest.mark.parametrize(('width','length','zoom','units'),[(640,1000,1,'frames'),(980,1000,1,'frames'),(640,300,6,'time'),(1440,12000,1,'time')])
def test_ticks_center_with_visible_separated_labels(application,monkeypatch,simple,width,length,zoom,units):
    import timeline_skin
    t=Timeline(); t.simple=simple; t.resize(width,100); t.set_units(units); t.zoom=zoom
    t.set_document(State((Segment('a',0,length),)),{},24)
    captured=[]; original=timeline_skin.label
    def read(p,area,text,*args,**kwargs):
        if len(args)>=3 and args[:3]==('#9cabb9',10,True): captured.append((area,text))
        return original(p,area,text,*args,**kwargs)
    monkeypatch.setattr(timeline_skin,'label',read)
    for offset in (0,length-t.span()):
        t.view_start=offset; captured.clear(); t.grab()
        centers=[t.x_for(frame)+(0 if simple else .5) for frame,_,large in ruler_ticks(t) if large]
        tolerance=.5/t.devicePixelRatioF()+.01 if simple else .01
        assert captured
        for i,(area,text) in enumerate(captured):
            assert min(abs(area.center().x()-x) for x in centers)<=tolerance
            assert 0<=area.left() and area.right()<width
            if i: assert area.left()>=captured[i-1][0].right()+3
    t.deleteLater()


def test_fractional_zoom_keeps_compact_ticks_uniform(application):
    t=Timeline(); t.simple=True; t.resize(900,42); t.set_units('frames')
    cuts=(0,99,201,341,404,421,493,666,800,935,1000)
    clips=tuple(Segment('a',0,b-a,cut_before=True) for a,b in zip(cuts,cuts[1:]))
    t.set_document(State(clips),{},24)
    profiles={False:set(),True:set()}; ratio=t.devicePixelRatioF()
    for zoom in (1.,1.3,1.69,2.197,3.71293,5.72):
        t.zoom=zoom; t.view_start=(1000-t.span())*.37
        bar=t.simple_track_rect(); y=math.floor(bar.center().y()*ratio)
        image=t.grab().toImage()
        for frame,_,major in ruler_ticks(t):
            x=t.x_for(frame)
            if min(x-bar.left(),bar.right()-x)<10 or any(abs(t.x_for(c)-x)<10 for c in cuts): continue
            centre=round(x*ratio); radius=math.ceil(4*ratio)
            pixels=[image.pixelColor(i,y).red() for i in range(centre-radius,centre+radius+1)]
            profiles[major].add(tuple(value for value in pixels if value<45))
    for major,items in profiles.items():
        assert len(items)==1
        ink,=items
        assert sum((45-value)/45 for value in ink)==pytest.approx((2 if major else .75)*ratio,abs=.07)
    t.deleteLater()
