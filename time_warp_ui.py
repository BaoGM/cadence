# SPDX-License-Identifier: GPL-3.0-only
from bisect import bisect_right
from dataclasses import replace
from pathlib import Path
import math
import tempfile
import threading
import time

from PySide6.QtCore import QPointF, QRectF, QSignalBlocker, QThread, QTimer, Qt, Signal, QSettings
from PySide6.QtGui import QColor, QFontMetrics, QImage, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSlider, QSpinBox, QVBoxLayout, QWidget)

from studio_icons import icon
from time_warp import METHODS, mapping, normalized, target, video_sample
from ui_text import tr


METHOD_LABELS=('Poses d’origine','Fondu','Mouvement (CPU)','RIFE','NVIDIA NvOFFRUC')


def reverse_axis(curve, last):
    return tuple((last-x,y,curve[i-1][2] if i else 'held')
                 for i,(x,y,_) in reversed(list(enumerate(curve))))


def knot_at(curve, x):
    i=bisect_right(curve,x,key=lambda p:p[0])-1
    if i>=0 and curve[i][0]==x: return curve[i]
    base,fraction,method=mapping(curve,x)
    return x,base+fraction if fraction else base,method


def visible_curve(clip):
    lo,hi=clip.start,clip.end-1
    curve=clip.warp
    ticks={lo,hi}
    if curve:
        ticks.update(x for x,_,_ in curve if lo<x<hi)
        # The model passes through the original frames outside a stored curve.
        ticks.update(x for x in (curve[0][0]-1,curve[-1][0]+1) if lo<x<hi)
    local=tuple((x-lo,y,m) for x,y,m in (knot_at(curve,x) for x in sorted(ticks)))
    return reverse_axis(local,hi-lo) if clip.reversed else local


def merge_visible_curve(clip, local):
    lo,hi=clip.start,clip.end-1
    curve=clip.warp
    visible=reverse_axis(local,hi-lo) if clip.reversed else local
    knots={x:(x,y,m) for x,y,m in curve if x<lo or x>hi}
    knots.update((lo+x,(lo+x,y,m)) for x,y,m in visible)
    if curve:
        first,last=curve[0][0],curve[-1][0]
        # Joining disjoint regions must keep the identity run beyond the old curve.
        if last+1<lo: knots[last+1]=knot_at(curve,last+1)
        if first-1>hi: knots[first-1]=knot_at(curve,first-1)
        if first<lo and knots[lo][1]!=knot_at(curve,lo)[1]:
            knots[lo-1]=knot_at(curve,lo-1)
        if hi<last:
            _,old_y,outgoing=knot_at(curve,hi)
            knots[hi]=(hi,knots[hi][1],outgoing)
            if knots[hi][1]!=old_y: knots[hi+1]=knot_at(curve,hi+1)
        elif hi==last:
            knots[hi]=(hi,knots[hi][1],curve[-1][2])
    return normalized(tuple(knots[x] for x in sorted(knots)))


class SourceFrameSpin(QDoubleSpinBox):
    def textFromValue(self,value):
        text=super().textFromValue(value)
        decimal=self.locale().decimalPoint()
        return text.rstrip(self.locale().zeroDigit()).rstrip(decimal) if decimal in text else text


class CurveView(QWidget):
    picked=Signal(int)
    moved=Signal(int,int)
    added=Signal(int,int)
    def __init__(self,parent):
        super().__init__(parent)
        self.editor=parent
        self.drag=False
        font=self.font()
        font.setPixelSize(10)
        metrics=QFontMetrics(font)
        self.left_margin=max(42,metrics.horizontalAdvance(str(parent.info['frames']-1))+8)
        self.right_margin=max(17,metrics.horizontalAdvance(str(parent.last))//2+3)
        self.setMinimumHeight(106)
        self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
        self.setAccessibleName(tr('Courbe temporelle'))

    def box(self):
        return QRectF(self.left_margin,14,max(1,self.width()-self.left_margin-self.right_margin),
                      max(1,self.height()-39))

    def pixel(self,x,y):
        b=self.box(); e=self.editor
        return QPointF(b.left()+b.width()*x/e.last,b.bottom()-b.height()*(y-e.low)/(e.high-e.low))

    def coordinates(self,pos):
        b=self.box(); e=self.editor
        return (max(0,min(e.last,round((pos.x()-b.left())/b.width()*e.last))),
                max(e.low,min(e.high,e.low+round((b.bottom()-pos.y())/b.height()*(e.high-e.low)))))

    def paintEvent(self,event):
        p=QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(),QColor('#11171e'))
        b=self.box(); e=self.editor
        f=p.font(); f.setPixelSize(10); p.setFont(f)
        for tick in sorted({round(i*e.last/4) for i in range(5)}):
            x=self.pixel(tick,e.low).x()
            p.setPen(QColor('#2b3641')); p.drawLine(QPointF(x,b.top()),QPointF(x,b.bottom()))
            p.setPen(QColor('#acbac9'))
            p.drawText(QRectF(x-self.right_margin,b.bottom()+3,2*self.right_margin,17),Qt.AlignCenter,str(tick))
        for tick in sorted({e.low+round(i*(e.high-e.low)/4) for i in range(5)}):
            y=self.pixel(0,tick).y()
            p.setPen(QColor('#2b3641')); p.drawLine(QPointF(b.left(),y),QPointF(b.right(),y))
            p.setPen(QColor('#acbac9'))
            p.drawText(QRectF(0,y-9,self.left_margin-6,18),Qt.AlignRight|Qt.AlignVCenter,str(tick))
        p.setPen(QPen(QColor('#647583'),1,Qt.DashLine))
        original=(e.clip.source_frame(0),e.clip.source_frame(e.last))
        p.drawLine(self.pixel(0,original[0]),self.pixel(e.last,original[1]))
        at=self.pixel(e.scrub.value(),e.low).x()
        p.setPen(QPen(QColor('#cfa279'),1))
        p.drawLine(QPointF(at,b.top()),QPointF(at,b.bottom()))
        nodes=[self.pixel(x,y) for x,y,_ in e.curve]
        p.setPen(QPen(QColor('#68e0cf'),2))
        for a,z in zip(nodes,nodes[1:]): p.drawLine(a,z)
        for i,node in enumerate(nodes):
            p.setBrush(QColor('#f5b66e' if i==e.selected else '#16272d'))
            p.drawEllipse(node,4.5,4.5)

    def mousePressEvent(self,event):
        if event.button()!=Qt.LeftButton: return
        e=self.editor
        e.drag_saved=False
        distances=[(self.pixel(x,y)-event.position()).manhattanLength() for x,y,_ in e.curve]
        i=min(range(len(distances)),key=distances.__getitem__)
        if distances[i]<=16:
            self.drag=True; self.picked.emit(i)
        else: e.scrub.setValue(self.coordinates(event.position())[0])

    def mouseMoveEvent(self,event):
        if self.drag: self.moved.emit(*self.coordinates(event.position()))

    def mouseReleaseEvent(self,event):
        self.drag=False

    def mouseDoubleClickEvent(self,event):
        if event.button()==Qt.LeftButton: self.added.emit(*self.coordinates(event.position()))


class WarpPreview(QThread):
    ready=Signal(int,object,object)
    failed=Signal(int,str)
    def __init__(self,info,clip):
        super().__init__()
        self.info,self.clip=info,clip
        self.condition=threading.Condition()
        self.pending=None
        self.cancel=threading.Event()
        self.stopping=False

    def request(self,args):
        with self.condition:
            self.cancel.set()
            self.pending=args
            self.condition.notify()

    def stop(self):
        with self.condition:
            self.stopping=True
            self.cancel.set()
            self.condition.notify()
        self.wait()

    def run(self):
        from media import PreviewReader,Cancelled
        from time_warp_render import Samples,rgb_info
        import numpy as np
        reader=PreviewReader()
        original=self.info
        width=original.get('proxy_width',original['width'])
        height=original.get('proxy_height',original['height'])
        scale=min(1,640/width,400/height)
        small=dict(original,proxy_width=max(2,round(width*scale/2)*2),proxy_height=max(2,round(height*scale/2)*2))
        try:
            with tempfile.TemporaryDirectory(prefix='cadence-warp-view-') as folder:
                while True:
                    with self.condition:
                        while self.pending is None and not self.stopping: self.condition.wait()
                        if self.stopping: return
                        serial,curve,frame,raw,existing=self.pending; self.pending=None
                        self.cancel=threading.Event()
                        cancel=self.cancel
                    try:
                        reference=reader.read(small,raw)
                        if existing:
                            info,index=video_sample(original,self.clip,raw)
                            a=reader.read(dict(info,proxy_width=small['proxy_width'],proxy_height=small['proxy_height']),index)
                        else:
                            base,frac,method=mapping(curve,frame)
                            a=reader.read(small,base)
                            if frac and method!='held':
                                b=reader.read(small,base+1)
                                if method=='blend':
                                    a=np.rint(a.astype(np.float32)*(1-frac)+b*frac).astype(np.uint8)
                                else:
                                    class Pair:
                                        def read(self,source,index): return (a,b)[index]
                                    source=rgb_info('',original['fps'],2,a.shape[1],a.shape[0])
                                    samples=Samples(Path(folder),source,Pair(),cancel)
                                    try: a=samples.sample(0,frac,method)
                                    finally: samples.release_block()
                        if not cancel.is_set(): self.ready.emit(serial,a,reference)
                    except Cancelled: pass
                    except Exception as exc:
                        if not cancel.is_set(): self.failed.emit(serial,str(exc))
        finally: reader.close()


class WarpDialog(QDialog):
    def __init__(self,window,clip,info,offset=0):
        super().__init__(window)
        self.setWindowTitle('Time Warp · '+Path(info['path']).name)
        self.clip,self.info=clip,info
        self.last=clip.length-1
        self.curve=visible_curve(clip)
        self.low=math.floor(min(clip.start,*(p[1] for p in self.curve)))
        self.high=math.ceil(max(clip.end-1,*(p[1] for p in self.curve)))
        self.initial=self.curve
        self.merged_local=self.curve
        self.merged_curve=clip.warp
        self.selected=0
        self.serial=0
        self.images=None
        self.playing=False
        self.current_preset=0
        self.undo_values=[]; self.redo_values=[]
        self.resize(830,620)
        box=QVBoxLayout(self)
        media=QHBoxLayout(); box.addLayout(media,3)
        self.screens=[]
        for title in ('Time Warp','Original'):
            pane=QWidget()
            column=QVBoxLayout(pane)
            column.setContentsMargins(0,0,0,0)
            media.addWidget(pane,1)
            panel=QLabel(tr(title)); panel.setAlignment(Qt.AlignCenter); column.addWidget(panel)
            screen=QLabel(); screen.setMinimumSize(55,55); screen.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Ignored)
            screen.setStyleSheet('background:#0d1116'); screen.setAlignment(Qt.AlignCenter); column.addWidget(screen,1)
            self.screens.append((panel,screen))
        row=QHBoxLayout();box.addLayout(row)
        self.play=QPushButton(); self.play.setIcon(icon('play')); self.play.setAccessibleName(tr('Lecture'))
        self.play.clicked.connect(self.toggle_play);row.addWidget(self.play)
        self.scrub=QSlider(Qt.Horizontal); self.scrub.setRange(0,self.last); row.addWidget(self.scrub,1)
        self.readout=QLabel();row.addWidget(self.readout)
        self.compare=QCheckBox('A/B');self.compare.setChecked(True);self.compare.toggled.connect(self.compare_changed);row.addWidget(self.compare)
        row=QHBoxLayout();box.addLayout(row)
        row.addWidget(QLabel(tr('Courbe temporelle')));row.addStretch()
        self.presets=QComboBox()
        self.presets.addItems([tr(v) for v in ('Personnalisé','Vitesse normale','Pose tenue et ralenti','Lecture inversée')])
        self.presets.activated.connect(self.preset);row.addWidget(self.presets)
        self.graph=CurveView(self);box.addWidget(self.graph,2)
        self.graph.picked.connect(self.pick);self.graph.moved.connect(self.move_point);self.graph.added.connect(self.add_point)
        row=QHBoxLayout();box.addLayout(row)
        self.add=QPushButton(tr('Ajouter un point'));self.add.clicked.connect(self.add_here);row.addWidget(self.add)
        self.remove=QPushButton(tr('Retirer le point'));self.remove.clicked.connect(self.remove_point);row.addWidget(self.remove)
        row.addStretch()
        form=QFormLayout();box.addLayout(form)
        row=QHBoxLayout()
        self.x=QSpinBox();self.y=SourceFrameSpin();self.y.setDecimals(6)
        self.y.setRange(0,info['frames']-1)
        self.y.setSingleStep(1)
        row.addWidget(self.x);row.addWidget(QLabel(tr('Image source')));row.addWidget(self.y)
        form.addRow(tr('Image du montage'),row)
        row=QHBoxLayout()
        self.method=QComboBox();self.method.addItems([tr(m) for m in METHOD_LABELS]);row.addWidget(self.method,1)
        self.engine_button=QPushButton('…');self.engine_button.setFixedWidth(32)
        self.engine_button.setToolTip(tr('Choisir le moteur local'));self.engine_button.clicked.connect(self.choose_engine)
        row.addWidget(self.engine_button);form.addRow(tr('Interpolation du segment'),row)
        self.x.valueChanged.connect(lambda v:self.move_point(v,self.curve[self.selected][1]))
        self.y.valueChanged.connect(lambda v:self.move_point(self.x.value(),v))
        self.method.activated.connect(self.change_method)
        self.status=QLabel();self.status.setWordWrap(True);self.status.hide();box.addWidget(self.status)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr('Appliquer'));buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject);box.addWidget(buttons)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.advance)
        self.worker=WarpPreview(info,clip);self.worker.ready.connect(self.received);self.worker.failed.connect(self.failed);self.worker.start()
        for seq,fn in [('Space',self.toggle_play),('Left',lambda:self.scrub.setValue(self.scrub.value()-1)),
                       ('Right',lambda:self.scrub.setValue(self.scrub.value()+1)),('Ctrl+Z',lambda:self.history(False)),
                       ('Ctrl+Shift+Z',lambda:self.history(True))]:
            QShortcut(QKeySequence(seq),self,activated=fn)
        self.scrub.setValue(max(0,min(self.last,offset)))
        self.scrub.valueChanged.connect(self.refresh)
        self.pick(min(range(len(self.curve)),key=lambda i:abs(self.curve[i][0]-self.scrub.value())),False)

    def compare_changed(self,enabled):
        self.screens[1][1].parentWidget().setVisible(enabled)
        QTimer.singleShot(0,self.paint_images)

    def stored_curve(self):
        if self.curve is not self.merged_local:
            self.merged_curve=self.clip.warp if self.curve==self.initial else merge_visible_curve(self.clip,self.curve)
            self.merged_local=self.curve
        return self.merged_curve

    def pick(self,i,seek=True):
        self.selected=i
        x,y,method=self.curve[i]
        inner=0<i<len(self.curve)-1
        with QSignalBlocker(self.x),QSignalBlocker(self.y):
            self.x.setRange(self.curve[i-1][0]+1 if inner else x,self.curve[i+1][0]-1 if inner else x)
            self.x.setValue(x);self.x.setEnabled(inner);self.y.setValue(y)
        self.remove.setEnabled(inner)
        if seek: self.scrub.setValue(x)
        self.refresh()

    def changed(self,new,i,seek=True,preset=0):
        new=tuple(new)
        if new==self.curve:
            if preset:
                self.current_preset=preset
                self.presets.setCurrentIndex(preset)
            return
        try: merged=self.clip.warp if new==self.initial else merge_visible_curve(self.clip,new)
        except ValueError as exc:
            self.pick(self.selected,False)
            self.presets.setCurrentIndex(self.current_preset)
            self.status.setText(tr(str(exc)));self.status.show()
            return
        if not self.graph.drag or not getattr(self,'drag_saved',False):
            self.undo_values.append((self.curve,self.selected,self.current_preset))
            self.undo_values=self.undo_values[-100:]
        self.drag_saved=self.graph.drag
        self.redo_values.clear()
        self.low=min(self.low,math.floor(min(y for _,y,_ in new)))
        self.high=max(self.high,math.ceil(max(y for _,y,_ in new)))
        self.merged_local,self.merged_curve=new,merged
        self.curve=new;self.current_preset=preset;self.presets.setCurrentIndex(preset);self.pick(i,seek)

    def history(self,redo):
        source,to=(self.redo_values,self.undo_values) if redo else (self.undo_values,self.redo_values)
        if source:
            to.append((self.curve,self.selected,self.current_preset))
            self.curve,i,self.current_preset=source.pop()
            self.presets.setCurrentIndex(self.current_preset)
            self.pick(i)

    def move_point(self,x,y):
        i=self.selected;old,_,method=self.curve[i]
        x=max(self.curve[i-1][0]+1,min(self.curve[i+1][0]-1,x)) if 0<i<len(self.curve)-1 else old
        c=list(self.curve);c[i]=(x,y,method);self.changed(c,i)

    def add_point(self,x,y):
        if not 0<x<self.last: return
        i=bisect_right(self.curve,x,key=lambda p:p[0])
        if self.curve[i-1][0]==x: self.pick(i-1);return
        self.changed(self.curve[:i]+((x,y,self.curve[i-1][2]),)+self.curve[i:],i)

    def add_here(self):
        x=self.scrub.value();base,frac,_=mapping(self.stored_curve(),self.clip.source_frame(x));self.add_point(x,base+frac)

    def remove_point(self):
        i=self.selected
        if 0<i<len(self.curve)-1: self.changed(self.curve[:i]+self.curve[i+1:],i-1)

    def preset(self,i):
        if not i:
            self.current_preset=0
            return
        stops=([(0,0),(1,1)] if i==1 else [(0,0),(.25,.25),(.55,.25),(1,.7)] if i==2 else [(0,1),(1,0)])
        nodes={round(t*self.last):self.clip.source_frame(round(y*self.last)) for t,y in stops}
        self.changed([(t,y,'held') for t,y in sorted(nodes.items())],0,preset=i)

    def segment(self):
        return min(len(self.curve)-2,bisect_right(self.curve,self.scrub.value(),key=lambda p:p[0])-1)

    def change_method(self,index):
        i=self.segment();x,y,_=self.curve[i]
        c=list(self.curve);c[i]=(x,y,METHODS[index]);self.changed(c,self.selected,False)

    def choose_engine(self):
        method=self.curve[self.segment()][2]
        name='rife-ncnn-vulkan.exe' if method=='rife' else 'NVEncC64.exe'
        exe,_=QFileDialog.getOpenFileName(self,tr('Choisir le moteur local'),'',name+' ('+name+')')
        if exe and Path(exe).name.lower()==name.lower():
            QSettings('CadenceStudio','Interpolation').setValue(method,exe);self.refresh()

    def refresh(self):
        if not hasattr(self,'worker'): return
        at=self.scrub.value();raw=self.clip.source_frame(at)
        curve=self.stored_curve()
        base,frac,_=mapping(curve,raw)
        method=self.curve[self.segment()][2];self.method.setCurrentIndex(METHODS.index(method))
        self.engine_button.setVisible(method in ('rife','nvidia'))
        self.readout.setText(f'{at}  →  {base+frac:.2f}'.rstrip('0').rstrip('.'))
        self.graph.update();self.serial+=1
        self.requested_at=time.monotonic()
        self.worker.request((self.serial,curve,raw,raw,
                             bool(self.clip.warp and self.curve==self.initial)))

    def received(self,serial,a,b):
        if serial!=self.serial: return
        self.status.hide()
        import numpy as np
        self.images=[]
        for rgb in (a,b):
            rgb=np.ascontiguousarray(rgb)
            fmt=QImage.Format_RGBA8888 if rgb.shape[2]==4 else QImage.Format_RGB888
            self.images.append(QImage(rgb.data,rgb.shape[1],rgb.shape[0],rgb.strides[0],fmt).copy())
        self.paint_images()
        if self.playing:
            wait=1/float(self.parent().doc.fps)-(time.monotonic()-self.requested_at)
            self.timer.start(max(1,round(1000*wait)))

    def paint_images(self):
        from PySide6.QtGui import QPixmap
        if self.images:
            for img,(_,label) in zip(self.images,self.screens):
                label.setPixmap(QPixmap.fromImage(img).scaled(label.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))

    def resizeEvent(self,event):
        super().resizeEvent(event);self.paint_images()

    def failed(self,serial,message):
        if serial==self.serial:
            self.status.setText(tr(message));self.status.show();self.playing=False;self.timer.stop();self.play.setIcon(icon('play'))

    def advance(self):
        if self.playing: self.scrub.setValue((self.scrub.value()+1)%(self.last+1))

    def toggle_play(self):
        self.playing=not self.playing;self.play.setIcon(icon('pause' if self.playing else 'play'))
        if self.playing: self.advance()
        else: self.timer.stop()

    def done(self,code):
        self.timer.stop();self.playing=False;self.worker.stop()
        super().done(code)


def open_editor(window):
    if window.job: return
    doc=window.doc
    hit=target(doc)
    if not hit: return
    track,index,start,clip=hit
    window.pause()
    dlg=WarpDialog(window,clip,doc.media[clip.media],doc.state.position-start)
    try:
        if dlg.exec()!=QDialog.Accepted or dlg.curve==dlg.initial: return
        curve=dlg.stored_curve()
    finally:
        dlg.worker.stop();dlg.deleteLater()
    if curve==clip.warp: return
    def apply(_=None):
        if window.doc is not doc: return
        current=next((t for t in doc.state.tracks if t.info.id==track.info.id),None)
        if not current or index>=len(current.segments) or current.segments[index]!=clip: return
        segments=list(current.segments);segments[index]=replace(clip,warp=curve)
        from model import with_tracks
        # Time Warp remaps the picture. Audio keeps its source sample positions.
        video=tuple(segments)
        replacement=replace(current,segments=video,audio_segments=None if current.audio==video else current.audio)
        doc.commit('Time Warp',with_tracks(doc.state,tuple(replacement if t.info.id==current.info.id else t for t in doc.state.tracks)))
        window.refresh();window.request_frame()
    if curve:
        from time_warp_render import ensure_render
        window.begin_task('Calcul du Time Warp',lambda p,c:ensure_render(doc.media[clip.media],curve,p,c),apply)
    else: apply()
