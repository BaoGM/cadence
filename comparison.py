# SPDX-License-Identifier: GPL-3.0-only
"""Synchronized A/B review controls and pixel comparison, independent of export."""
from ui_text import tr
from fractions import Fraction
from math import floor
import numpy as np
from PySide6.QtCore import Qt,QSignalBlocker,QRectF,QPointF
from PySide6.QtGui import QImage,QPainter,QPainterPath
from PySide6.QtWidgets import QWidget,QDockWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QComboBox,QPushButton,QCheckBox,QFileDialog,QScrollArea
from widgets import ScrubSpinBox,ScrubDoubleSpinBox,TransportButton
from engine import Decoder
from media import prepare_media

MODES=[('Côte à côte','horizontal'),('Dessus / dessous','vertical'),('Overlay - transparence','overlay'),('Différence - négatif','difference'),('Révélateur','wipe'),('A devant B - bascule','front')]

class ComparisonButton(TransportButton):
    def __init__(self,symbol,callback):
        super().__init__(symbol,callback,name='comparisonControl')
        self.setFixedSize(36,34)
    def draw_symbol(self,p,color):
        pen=p.pen(); pen.setWidthF(1.6); p.setPen(pen)
        def frame(x,y,w,h): p.drawRoundedRect(QRectF(x,y,w,h),.5,.5)
        def letter(text,x,y):
            font=p.font(); font.setPixelSize(10); font.setBold(True); p.setFont(font)
            p.drawText(QRectF(x,y,10,14),Qt.AlignmentFlag.AlignCenter,tr(text))
        if self.symbol=='horizontal':
            frame(-12,-8,10,16); frame(2,-8,10,16)
        elif self.symbol=='vertical':
            frame(-10,-11,20,9); frame(-10,2,20,9)
        elif self.symbol=='overlay':
            p.setOpacity(.45); p.fillRect(QRectF(-11,-10,16,14),color)
            p.setOpacity(.65); p.fillRect(QRectF(-5,-4,16,14),color)
            p.setOpacity(1); frame(-11,-10,16,14); frame(-5,-4,16,14)
        elif self.symbol=='wipe':
            frame(-11,-9,22,18); p.drawLine(QPointF(0,-12),QPointF(0,12)); p.drawEllipse(QPointF(0,0),3,3)
        elif self.symbol=='difference':
            frame(-11,-9,22,18)
            half=QPainterPath(); half.addRect(QRectF(0,-9,10,18)); half.addRoundedRect(QRectF(3,-.8,4,1.6),.8,.8); p.fillPath(half,color)
            p.drawLine(QPointF(-7,0),QPointF(-3,0))
        elif self.symbol in ('front_a','front_b'):
            path=QPainterPath(); path.moveTo(-12,4); path.lineTo(-12,-11); path.lineTo(5,-11); p.drawPath(path)
            frame(-7,-6,19,17); letter('B' if self.symbol=='front_b' else 'A',-2,-5)
        elif self.symbol in ('ab','ba'):
            first,second=('A','B') if self.symbol=='ab' else ('B','A')
            letter(first,-13,-7); letter(second,3,-7)
            path=QPainterPath(); path.moveTo(-10,-10); path.lineTo(10,-10); path.lineTo(6,-13)
            path.moveTo(10,10); path.lineTo(-10,10); path.lineTo(-6,13); p.drawPath(path)
        else:
            frame(-11,-8,22,16); letter('A',-5,-7)

def fit_reference(rgb,width,height):
    if rgb.shape[:2]==(height,width): return rgb
    rgb=np.ascontiguousarray(rgb)
    image=QImage(rgb.data,rgb.shape[1],rgb.shape[0],rgb.strides[0],QImage.Format.Format_RGB888)
    scaled=image.scaled(width,height,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
    target=QImage(width,height,QImage.Format.Format_RGB888); target.fill(Qt.GlobalColor.black)
    painter=QPainter(target); painter.drawImage((width-scaled.width())//2,(height-scaled.height())//2,scaled); painter.end()
    return np.frombuffer(target.bits(),np.uint8).reshape(height,target.bytesPerLine())[:,:width*3].reshape(height,width,3).copy()

def compose(a,b,mode,opacity=.5,gain=1.,swapped=False,wipe=.5):
    b=fit_reference(b,a.shape[1],a.shape[0])
    if swapped: a,b=b,a
    if mode=='wipe':
        output=a.copy(); x=round(a.shape[1]*max(0,min(1,wipe))); output[:,x:]=b[:,x:]; return output
    if mode=='horizontal': return np.concatenate((a,b),axis=1)
    if mode=='vertical': return np.concatenate((a,b),axis=0)
    if mode in ('overlay','difference'):
        output=np.empty_like(a)
        for start in range(0,a.shape[0],64):
            aa=a[start:start+64]; bb=b[start:start+64]
            if mode=='overlay':
                blend=aa.astype(np.float32); blend*=1-opacity
                other=bb.astype(np.float32); other*=opacity; blend+=other
                np.rint(blend,out=blend); np.clip(blend,0,255,out=blend)
                output[start:start+64]=blend
            else:
                delta=np.subtract(aa,bb,dtype=np.int16); np.abs(delta,out=delta)
                if gain==1: output[start:start+64]=delta
                else:
                    values=delta*gain; np.clip(values,0,255,out=values); output[start:start+64]=values
        return output
    return a

from reference_panel import ReferenceQueueMixin
from reference_sequence import ReferenceSequence,snapshot as reference_snapshot

class ComparisonMixin(ReferenceQueueMixin):
    def build_comparison(self):
        self.compare_media=None; self.reference_order=[]; self.reference_index=ReferenceSequence(); self.reference_sources={}; self.reference_signature=None; self.comparison_pending=None
        self.reference_decoder=Decoder(self); self.reference_decoder.ready.connect(self.reference_ready); self.reference_decoder.failed.connect(self.reference_failed); self.reference_decoder.start()
        self.comparison_panel=QDockWidget(tr('Comparaison'),self); self.comparison_panel.setObjectName('comparison'); self.comparison_panel.setMinimumWidth(200)
        body=QWidget(); col=QVBoxLayout(body); col.setContentsMargins(16,12,16,12)
        col.addWidget(QLabel(tr('COMPARAISON A / B')))
        self.compare_enabled=QCheckBox(tr('Activer la comparaison')); col.addWidget(self.compare_enabled)
        self.reference_combo=QComboBox(); self.reference_combo.setMinimumContentsLength(18); self.reference_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon); col.addWidget(self.reference_combo)
        open_button=QPushButton(tr('Ajouter des références B…')); open_button.clicked.connect(self.open_reference); col.addWidget(open_button)
        self.compare_mode=QComboBox()
        for title,mode in MODES: self.compare_mode.addItem(tr(title),mode)
        col.addWidget(self.compare_mode)
        swap=QPushButton(tr('Intervertir A / B')); swap.clicked.connect(self.swap_comparison); col.addWidget(swap)
        self.compare_opacity=ScrubSpinBox(); self.compare_opacity.setRange(0,100); self.compare_opacity.setValue(50); self.compare_opacity.setSuffix(tr(' %'))
        self.compare_gain=ScrubDoubleSpinBox(); self.compare_gain.setRange(1,20); self.compare_gain.setValue(1); self.compare_gain.setSingleStep(.5); self.compare_gain.setSuffix(tr(' ×'))
        self.compare_offset=ScrubSpinBox(); self.compare_offset.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu); self.compare_offset.lineEdit().setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu); self.compare_offset.setRange(-1000000,1000000); self.compare_offset.setValue(0); self.compare_offset.setToolTip(tr('Image B lue au temps du montage + décalage. Les cadences différentes sont synchronisées en secondes.'))
        values=QGridLayout(); values.setColumnStretch(1,1); values.setHorizontalSpacing(10); values.setVerticalSpacing(6)
        for row,(title,field) in enumerate((('Opacité',self.compare_opacity),('Gain',self.compare_gain),('Décalage référence',self.compare_offset))):
            label=QLabel(tr(title)); label.setBuddy(field); values.addWidget(label,row,0); values.addWidget(field,row,1)
        col.addLayout(values)
        align=QPushButton(tr('Début de B au curseur actuel')); align.clicked.connect(lambda:self.compare_offset.setValue(-self.doc.state.position)); col.addWidget(align)
        col.addStretch()
        scroll=QScrollArea(); scroll.setWidget(body); scroll.setWidgetResizable(True); self.comparison_panel.setWidget(scroll); self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,self.comparison_panel); self.comparison_panel.hide()
        self.compare_enabled.toggled.connect(self.comparison_changed); self.reference_combo.currentIndexChanged.connect(self.choose_reference)
        self.compare_mode.currentIndexChanged.connect(self.comparison_visual_changed); self.compare_opacity.valueChanged.connect(self.comparison_visual_changed); self.compare_gain.valueChanged.connect(self.comparison_visual_changed); self.compare_offset.valueChanged.connect(self.comparison_changed)
        self.build_comparison_controls(); self.build_reference_list()
        self.refresh_reference_choices(); self.comparison_visual_changed()
    def build_comparison_controls(self):
        self.compare_controls=QWidget(); row=QHBoxLayout(self.compare_controls); row.setContentsMargins(3,0,0,0); row.setSpacing(1)
        self.compare_cycle_btn=ComparisonButton('off',self.cycle_comparison)
        self.compare_swap_btn=ComparisonButton('ab',self.swap_comparison)
        row.addWidget(self.compare_cycle_btn); row.addWidget(self.compare_swap_btn)
        self.transport_center.addWidget(self.compare_controls)
    def cycle_comparison(self):
        if self.editing_text(): return
        if not self.compare_enabled.isChecked():
            self.compare_mode.setCurrentIndex(0); self.compare_enabled.setChecked(True)
        elif self.compare_mode.currentIndex()==len(MODES)-1:
            self.compare_enabled.setChecked(False)
        else:
            self.compare_mode.setCurrentIndex(self.compare_mode.currentIndex()+1)
    def sync_comparison_controls(self):
        enabled=self.compare_enabled.isChecked(); mode=self.compare_mode.currentData(); swapped=self.viewer.compare_swapped
        symbol=('front_b' if swapped else 'front_a') if mode=='front' else mode
        self.compare_cycle_btn.setSymbol(symbol if enabled else 'off')
        title=('B devant A' if swapped else 'A devant B') if mode=='front' else self.compare_mode.currentText()
        current=title if enabled else 'Vidéo A seule'
        next_title=MODES[0][0] if not enabled else (MODES[self.compare_mode.currentIndex()+1][0] if self.compare_mode.currentIndex()<len(MODES)-1 else 'Vidéo A seule')
        tip=f'Comparaison : {current}\nClic : {next_title}'
        if not self.compare_media: tip+='\nChoisir une référence B dans les réglages.'
        self.compare_cycle_btn.setToolTip(tr(tip)); self.compare_cycle_btn.setAccessibleName(tr('Mode de comparaison : '+current))
        self.compare_swap_btn.setSymbol('ba' if swapped else 'ab'); self.compare_swap_btn.setEnabled(self.comparison_active())
        order='B / A' if swapped else 'A / B'; tip=f'Intervertir A / B · ordre actuel : {order}'
        self.compare_swap_btn.setToolTip(tr(tip)); self.compare_swap_btn.setAccessibleName(tr(tip))
    def comparison_menu(self):
        menu=self.menuBar().addMenu(tr('Comparaison'))
        self.compare_action=self.action(menu,'Activer la comparaison',lambda checked:self.compare_enabled.setChecked(checked),'Shift+C'); self.compare_action.setCheckable(True)
        self.action(menu,'Ajouter des références B…',self.open_reference,'Ctrl+Shift+B')
        self.action(menu,'Intervertir A / B',self.swap_comparison,'Alt+X')
        for index,(title,mode) in enumerate(MODES): self.action(menu,title,lambda checked=False,i=index:self.set_compare_mode(i))
    def set_compare_mode(self,index):
        self.compare_mode.setCurrentIndex(index); self.compare_enabled.setChecked(True); self.comparison_panel.show()
    def refresh_reference_choices(self):
        sources={**self.reference_sources,**self.doc.media}
        signature=(tuple((key,m['path']) for key,m in sources.items()),tuple(self.reference_order))
        if signature==self.reference_signature: return
        self.reference_signature=signature; selected='__sequence__' if len(self.reference_order)>1 else self.compare_media['id'] if self.compare_media else None
        with QSignalBlocker(self.reference_combo):
            self.reference_combo.clear(); self.reference_combo.addItem(tr('Choisir une référence…'),None)
            if len(self.reference_order)>1: self.reference_combo.addItem(tr('Liste de références')+f' ({len(self.reference_order)})','__sequence__')
            for key,m in sources.items():
                if m.get('has_video',True): self.reference_combo.addItem(m['name'],key)
            self.reference_combo.setCurrentIndex(max(0,self.reference_combo.findData(selected)))
    def choose_reference(self):
        key=self.reference_combo.currentData()
        if key=='__sequence__': return
        media=({**self.reference_sources,**self.doc.media}).get(key)
        self.set_reference_sequence([media] if media else [])
    def use_reference(self,media):
        self.set_reference_sequence([media]); self.comparison_panel.show()
    def open_reference(self):
        if self.job: return
        paths,_=QFileDialog.getOpenFileNames(self,tr('Ajouter des références B'),'',tr('Vidéos (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.mpg *.mpeg *.mts);;Tous les fichiers (*)'))
        if not paths: return
        quality=self.preferences.get('preview_quality','native')
        def prepare(progress,cancel):
            result=[]
            for index,path in enumerate(paths):
                media=prepare_media(path,progress=lambda value,message:progress((index+value)/len(paths),message),cancel=cancel,quality=quality)
                if media.get('has_video') is False: raise ValueError(tr('Une référence doit contenir une vidéo.'))
                result.append(media)
            return result
        def ready(entries):
            self.set_reference_sequence(entries,append=True); self.library.show(); self.library_tabs.setCurrentIndex(self.reference_tab)
        self.begin_task('Préparation des références B',prepare,ready)
    def comparison_active(self): return self.compare_enabled.isChecked() and self.compare_media is not None
    def comparison_visual_changed(self,*args):
        self.viewer.compare_mode=self.compare_mode.currentData(); self.viewer.compare_opacity=self.compare_opacity.value()/100; self.viewer.compare_gain=self.compare_gain.value()
        self.viewer.apply_effect()
        self.sync_comparison_controls()
    def comparison_changed(self,*args):
        active=self.comparison_active(); self.viewer.comparing=active
        if hasattr(self,'compare_action'):
            with QSignalBlocker(self.compare_action): self.compare_action.setChecked(self.compare_enabled.isChecked())
        if self.compare_enabled.isChecked() and not self.compare_media:
            self.comparison_panel.show()
        self.comparison_visual_changed(); self.request_frame()
    def swap_comparison(self):
        if self.editing_text(): return
        self.viewer.compare_swapped=not self.viewer.compare_swapped; self.viewer.apply_effect(); self.sync_comparison_controls()
    def prepare_reference_frame(self,frame):
        if not self.comparison_active(): self.comparison_pending=None; return
        self.comparison_pending={'token':self.token,'a':None,'b':None}
        target=self.reference_index.locate(Fraction(frame+self.compare_offset.value(),1)/self.doc.fps)
        media=self.compare_media
        if target: slot,media,index=target
        if target and media.get('available') is not False:
            from media import prefetch_frames
            ahead=list(prefetch_frames(media,index,0,media['frames'],self.frame_cache.budget,backward=not self.transport.running))
            if media['frames']-index<24 and slot+1<len(self.reference_index.entries):
                following=self.reference_index.entries[slot+1]
                if following.get('available') is not False: ahead.extend((following,n) for n in range(min(4,following['frames'])))
            self.reference_decoder.request(self.token,media,index,ahead)
        else:
            self.comparison_pending['b']=np.zeros((max(2,round(640*media['height']/media['width'])),640,3),np.uint8)
    def reference_ready(self,token,arr):
        pending=self.comparison_pending
        if pending and token==self.token==pending['token']:
            pending['b']=arr; self.flush_comparison()
    def comparison_a_ready(self,token,arr):
        pending=self.comparison_pending
        if pending and token==self.token==pending['token']:
            pending['a']=arr; self.flush_comparison(); return True
        return False
    def flush_comparison(self):
        pending=self.comparison_pending
        if pending and pending['a'] is not None and pending['b'] is not None:
            self.viewer.reference_rgb=pending['b']; self.viewer.set_frame(pending['a']); self.rendered_token=pending['token']
    def reference_failed(self,token,message):
        if token==self.token:
            self.compare_enabled.setChecked(False); self.pause(); self.error('Référence B : '+message)

    def comparison_snapshot(self):
        config=dict(enabled=self.compare_enabled.isChecked(),reference=self.compare_media['path'] if self.compare_media else '',reference_cadence=self.compare_media.get('cadence') if self.compare_media else None,reference_fps=self.compare_media['fps'] if self.compare_media else None,mode=self.compare_mode.currentData(),opacity=self.compare_opacity.value(),gain=self.compare_gain.value(),offset=self.compare_offset.value(),swapped=self.viewer.compare_swapped,wipe=self.viewer.wipe_position)
        if len(self.reference_order)>1: config['references']=reference_snapshot(self.reference_entries())
        return config
    def restore_comparison(self,doc):
        config=doc.review; media=getattr(doc,'reference_media',None)
        entries=getattr(doc,'reference_sequence',[media] if media else [])
        self.reference_order=[entry['id'] for entry in entries]
        self.reference_sources={entry['id']:entry for entry in entries}
        self.reference_index=ReferenceSequence(entries)
        # View configuration is optional; malformed values fall back safely.
        def number(key,default,lo,hi):
            value=config.get(key,default)
            return max(lo,min(hi,value)) if isinstance(value,(int,float)) and not isinstance(value,bool) and np.isfinite(value) else default
        controls=(self.compare_mode,self.compare_opacity,self.compare_gain,self.compare_offset,self.compare_enabled)
        blockers=[QSignalBlocker(control) for control in controls]
        self.compare_media=media; self.viewer.reference_rgb=None; self.viewer.compare_swapped=config.get('swapped') is True
        self.viewer.wipe_position=number('wipe',.5,0,1)
        if media: self.reference_sources[media['id']]=media
        self.reference_signature=None; self.refresh_reference_choices(); self.refresh_reference_queue()
        self.compare_mode.setCurrentIndex(max(0,self.compare_mode.findData(config.get('mode','horizontal'))))
        self.compare_opacity.setValue(int(number('opacity',50,0,100))); self.compare_gain.setValue(number('gain',1,1,20)); self.compare_offset.setValue(int(number('offset',0,-1000000,1000000)))
        self.compare_enabled.setChecked(config.get('enabled') is True and media is not None)
        del blockers
        self.viewer.comparing=self.comparison_active(); self.comparison_visual_changed()
        if hasattr(self,'compare_action'):
            with QSignalBlocker(self.compare_action): self.compare_action.setChecked(self.compare_enabled.isChecked())
        if self.comparison_active(): self.comparison_panel.show()
        warning=getattr(doc,'reference_warning','')
        if warning: self.comparison_panel.show(); self.error('Référence B indisponible : '+warning)
