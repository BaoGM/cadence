# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from fractions import Fraction
import pytest
from PySide6.QtCore import Qt,QPoint
from PySide6.QtGui import QImage,QPainter,QKeySequence
from PySide6.QtTest import QTest
from test_drawing import application,window
from reference_sequence import ReferenceSequence,snapshot,restore
from model import Document,State,Segment
from media import Cancelled
from preferences import validate,defaults
from shortcut_defaults import CHANGES


def media(key,frames=24,fps='24'):
    return dict(id=key,path=key+'.mp4',name=key+'.mp4',frames=frames,fps=fps,width=640,height=360)


def test_sequence_exact_boundaries_mixed_rates():
    a,b,c=media('a'),media('b',60,'30'),media('c',24000,'24000/1001')
    sequence=ReferenceSequence([a,b,a,c])
    assert sequence.ends==[1,3,4,1005]
    assert sequence.locate(Fraction(23,24))==(0,a,23)
    assert sequence.locate(1)==(1,b,0)
    assert sequence.locate(Fraction(2999,1000))==(1,b,59)
    assert sequence.locate(3)==(2,a,0)
    assert sequence.locate(4)==(3,c,0)
    assert sequence.locate(1005) is None and sequence.locate(-1) is None


def test_reference_restore_order_duplicates_missing_and_cancel(monkeypatch):
    a,b=media('a'),media('b',60,'30'); doc=Document(); doc.review={'references':snapshot([b,a,b])}
    calls=[]
    def prepare(path,fps,**kwargs):
        calls.append(path); kwargs['progress'](.5,'test')
        return {'a.mp4':a,'b.mp4':b}[path]
    monkeypatch.setattr('reference_sequence.prepare_media',prepare)
    progress=[]; restore(doc,'native',lambda value,message:progress.append(value),lambda:False)
    assert doc.reference_sequence==[b,a,b] and calls==['b.mp4','a.mp4']
    assert progress==[pytest.approx(1/6),.5]
    doc.review={'reference':'a.mp4','reference_fps':'24'}
    restore(doc,'480p',lambda *_:None,lambda:False)
    assert doc.reference_sequence==[a]
    doc.review={'references':snapshot([a,b])}
    def missing(path,*args,**kwargs):
        if path=='a.mp4': raise FileNotFoundError(path)
        return b
    monkeypatch.setattr('reference_sequence.prepare_media',missing)
    restore(doc,'native',lambda *_:None,lambda:False)
    assert doc.reference_sequence[0]['available'] is False
    assert ReferenceSequence(doc.reference_sequence).locate(1)==(1,b,0)
    assert 'a.mp4' in doc.reference_warning
    def cancel(*args,**kwargs): raise Cancelled()
    monkeypatch.setattr('reference_sequence.prepare_media',cancel)
    with pytest.raises(Cancelled): restore(doc,'native',lambda *_:None,lambda:False)


def test_reference_queue_reorder_save_remove_without_stopping(window,monkeypatch,tmp_path):
    w=window; a,b=media('a'),media('b',60,'30')
    monkeypatch.setattr(w,'request_frame',lambda:None)
    w.set_reference_sequence([a,b,a]); w.doc.state=State((Segment('a',0,24),)); w.doc.media={'a':a}
    assert w.library_tabs.tabText(w.reference_tab)=='Références'
    assert w.reference_list.count()==3 and w.doc.dirty
    w.transport.running=True
    w.reference_list.item(1).setSelected(True); w.move_reference_items(-1)
    assert [m['id'] for m in w.reference_entries()]==['b','a','a']
    assert w.transport.running
    entry=w.reference_list.takeItem(2); w.reference_list.insertItem(0,entry); w.reference_reordered()
    assert [m['id'] for m in w.reference_entries()]==['a','b','a']
    assert w.transport.running
    w.doc.review=w.comparison_snapshot(); path=tmp_path/'refs.cadence'; w.doc.save(path)
    loaded=Document.load(path)
    assert loaded.format_version()==15 and not loaded.dirty
    assert loaded.review['references']==snapshot([a,b,a])
    loaded.reference_sequence=[a,b,a]; loaded.reference_media=a; w.restore_comparison(loaded)
    assert [m['id'] for m in w.reference_entries()]==['a','b','a']
    w.reference_list.selectAll(); w.remove_reference_items()
    assert w.reference_list.count()==0 and not w.comparison_active() and w.doc.dirty
    w.transport.running=False


def test_reference_request_boundary_offset_and_black(window,monkeypatch):
    w=window; a,b=media('a'),media('b',60,'30')
    monkeypatch.setattr(w,'request_frame',lambda:None)
    w.set_reference_sequence([a,b]); requests=[]
    monkeypatch.setattr(w.reference_decoder,'request',lambda *args:requests.append(args))
    w.prepare_reference_frame(23); assert requests[-1][1:3]==(a,23)
    assert any(m['id']=='b' and index==0 for m,index in requests[-1][3])
    w.prepare_reference_frame(24); assert requests[-1][1:3]==(b,0)
    w.prepare_reference_frame(48); assert requests[-1][1:3]==(b,30)
    w.compare_offset.setValue(-24); w.prepare_reference_frame(0)
    assert not w.comparison_pending['b'].any()
    w.prepare_reference_frame(48); assert requests[-1][1:3]==(b,0)
    w.compare_offset.setValue(0); w.prepare_reference_frame(72)
    assert not w.comparison_pending['b'].any()


def test_invalid_reference_project_rejected():
    data=Document().to_data()
    for entries in (None,{},[None],[{'path':42}]):
        data['comparison']={'references':entries}
        with pytest.raises(ValueError,match='références'): Document.from_data(data)


def test_defaults_migrate_without_overwriting_custom_keys(window):
    registry=window.action_registry; current=defaults(registry)
    normalized=validate(current,registry)
    assert all(QKeySequence(value)==QKeySequence(current['shortcuts'][key]) for key,value in normalized['shortcuts'].items())
    for key,(_,new) in CHANGES.items(): assert current['shortcuts'][key]==new
    old=dict(current); old.pop('shortcut_defaults_revision')
    old['shortcuts']=dict(current['shortcuts'])
    for key,(previous,_) in CHANGES.items(): old['shortcuts'][key]=previous
    old['shortcuts']['Dessin/Supprimer les clés']='Shift+Del'
    migrated=validate(old,registry)
    assert migrated['shortcuts']==normalized['shortcuts']
    old['shortcuts']['Outils/Curseur']='Alt+Q'
    old['shortcuts']['Outils/Pinceau']='C'
    custom=validate(old,registry)['shortcuts']
    assert custom['Outils/Curseur']=='Alt+Q' and custom['Outils/Pinceau']=='C'
    assert custom['Dessin/Copier les clés']==''


def test_simple_boundaries_and_animated_drag(window,application):
    w=window; w.request_frame=lambda:None
    w.doc.state=State((Segment('a',0,10),Segment('a',10,30),Segment(None,0,10)))
    t=w.timeline; t.simple=True; w.refresh(); t.resize(800,t.height())
    assert t.media_boundaries()==pytest.approx([t.x_for(10),t.x_for(30)])
    moves=[]; t.moved.disconnect(); t.moved.connect(lambda *args:moves.append(args))
    QTest.mousePress(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.AltModifier,QPoint(round(t.x_for(5)),35))
    QTest.mouseMove(t,QPoint(round(t.x_for(35)),35)); QTest.qWait(130)
    assert t.gesture=='move' and t.move_span==(0,10,'video') and t.drop_frame is not None
    picture=QImage(t.size(),QImage.Format.Format_ARGB32); picture.fill(Qt.GlobalColor.transparent)
    painter=QPainter(picture); t.render(painter,QPoint()); painter.end()
    assert any(picture.pixelColor(x,32).red()>180 and picture.pixelColor(x,32).green()>70 and picture.pixelColor(x,32).blue()<130 for x in range(20,t.width()-20))
    QTest.mouseRelease(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.AltModifier,QPoint(round(t.x_for(35)),35))
    assert len(moves)==1 and t.move_span is None
