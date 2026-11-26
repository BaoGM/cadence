# SPDX-License-Identifier: GPL-3.0-only
from ui_text import tr
import json
from PySide6.QtCore import Qt,QObject,QSignalBlocker,QByteArray,QTimer,QEvent
from PySide6.QtGui import QShortcut,QKeySequence
from PySide6.QtWidgets import QDockWidget, QCheckBox, QDialog, QVBoxLayout, QGridLayout, QLabel, QDialogButtonBox
from preferences import preference_path,write_file

def encoded(value): return bytes(value.toBase64()).decode('ascii')
def decoded(value):
    try: return QByteArray.fromBase64(value.encode('ascii')) if isinstance(value,str) and len(value)<1000000 else QByteArray()
    except UnicodeError: return QByteArray()

class WorkspaceModes(QObject):
    def __init__(self,w):
        super().__init__(w); self.w=w; self.mode='read'; self.path=preference_path().with_name('workspaces.json')
        self.pending_compact_mode=None; w.installEventFilter(self)
        self.panels={**w.panel_widgets(),'library':w.library,'tools':w.edit_toolbar}
        self.default_profiles={'read':{key:key in ('transport','timeline') for key in self.panels},
                               'edit':dict.fromkeys(self.panels,True)}
        self.profiles={mode:dict(values) for mode,values in self.default_profiles.items()}
        self.inspector_page={'read':'drawing','edit':'drawing'}
        self.library_pages={}
        self.simple={'read':True,'edit':False}; self.layouts={}; self.layout_versions={}; self.editable={'read':False,'edit':False}
        try:
            data=json.loads(self.path.read_text(encoding='utf-8'))
            sides=data.get('side_history',{})
            if isinstance(sides,dict):
                w.studio.side_history={k:list(dict.fromkeys('library' if n=='comparison' else n for n in v if n in ('library','drawing','comparison')))
                    for k,v in sides.items() if k in ('read/left','read/right','edit/left','edit/right') and isinstance(v,list)}
            for m in self.profiles:
                if data.get('inspector_page',{}).get(m)=='comments': self.inspector_page[m]='comments'
                for k in self.panels:
                    if type(data.get('profiles',{}).get(m,{}).get(k)) is bool: self.profiles[m][k]=data['profiles'][m][k]
                page=data.get('library_pages',{}).get(m)
                if type(page) is int and 0<=page<w.library_tabs.count(): self.library_pages[m]=page
                elif data.get('profiles',{}).get(m,{}).get('comparison') is True and not self.profiles[m]['library']:
                    self.profiles[m]['library']=True
                    self.library_pages[m]=w.reference_tab
                if type(data.get('simple',{}).get(m)) is bool: self.simple[m]=data['simple'][m]
                if isinstance(data.get('layouts',{}).get(m),str): self.layouts[m]=data['layouts'][m]
                self.layout_versions[m]=data.get('layout_versions',{}).get(m,0)
                self.editable[m]=data.get('editable',{}).get(m) is True
            initial=data.get('mode','read'); geometry=decoded(data.get('geometry'))
            if not geometry.isEmpty(): w.restoreGeometry(geometry)
        except (OSError,ValueError,TypeError,UnicodeError,AttributeError): initial='read'
        self.toggle=QCheckBox(tr('Mode édition')); self.toggle.setToolTip(tr('Décocher pour passer en mode lecture'))
        w.transport_left.addWidget(self.toggle); self.toggle.hide()
        self.toggle.toggled.connect(lambda checked:self.switch('edit' if checked else 'read'))
        w.timeline.simpleRequested.connect(self.set_timeline_simple)
        self.apply(initial if initial in self.profiles else 'read')
    def capture(self):
        self.profiles[self.mode]={k:not p.isHidden() for k,p in self.panels.items()}
        drawing=self.w.drawing
        self.inspector_page[self.mode]='comments' if drawing.inspector_tabs.currentWidget() is drawing.comments else 'drawing'
        self.library_pages[self.mode]=self.w.library_tabs.currentIndex()
        self.layouts[self.mode]=encoded(self.w.saveState()); self.editable[self.mode]=self.w.layout_editable
        self.layout_versions[self.mode]=2
    def save(self):
        write_file(self.path,dict(profiles=self.profiles,simple=self.simple,mode=self.mode,layouts=self.layouts,layout_versions=self.layout_versions,editable=self.editable,geometry=encoded(self.w.saveGeometry()),side_history=self.w.studio.side_history,inspector_page=self.inspector_page,library_pages=self.library_pages))
    def switch(self,mode):
        if mode==self.mode: return
        if self.w.video_fullscreen: self.w.toggle_fullscreen()
        self.capture(); self.apply(mode); self.save()
    def set_timeline_simple(self,simple):
        w=self.w; self.simple[self.mode]=bool(simple); w.timeline.simple=bool(simple)
        w.timeline.set_document(w.doc.state,w.doc.media,w.doc.fps); w.sync_timeline_scroll()
        w.studio.sync_mode(self.mode,bool(simple))
        self.capture(); self.save()
    def apply(self,mode):
        self.mode=mode; w=self.w; w.setUpdatesEnabled(False)
        try:
            if mode=='read': w.drawing.cancel(); w.drawing.choose_tool('cursor'); w.clip_tools.cancel()
            state=decoded(self.layouts.get(mode))
            w.restoreState(state if not state.isEmpty() else w.initial_dock_state)
            with QSignalBlocker(w.layout_action): w.layout_action.setChecked(self.editable[mode])
            w.set_layout_editable(self.editable[mode])
            tabs=w.drawing.inspector_tabs
            tabs.setCurrentIndex(tabs.indexOf(w.drawing.comments) if self.inspector_page[mode]=='comments' else 0)
            w.reference_return=None
            if mode in self.library_pages: w.library_tabs.setCurrentIndex(self.library_pages[mode])
            for k,p in self.panels.items(): p.setVisible(self.profiles[mode][k])
            if state.isEmpty() or self.layout_versions.get(mode,0)<2:
                self.layouts[mode]=encoded(w.saveState()); self.layout_versions[mode]=2
                self.pending_compact_mode=mode
                if w.isVisible(): self.schedule_compact_layout(mode)
            with QSignalBlocker(self.toggle): self.toggle.setChecked(mode=='edit')
            w.timeline.simple=self.simple[mode]; w.timeline.set_document(w.doc.state,w.doc.media,w.doc.fps); w.sync_timeline_scroll()
            w.studio.sync_mode(mode,self.simple[mode])
            w.viewer.setFocus(Qt.FocusReason.OtherFocusReason)
        finally: w.setUpdatesEnabled(True); w.update()
    def eventFilter(self,obj,event):
        if obj is self.w and event.type()==QEvent.Type.Show and self.pending_compact_mode:
            self.schedule_compact_layout(self.pending_compact_mode)
        return super().eventFilter(obj,event)
    def schedule_compact_layout(self,mode):
        QTimer.singleShot(0,lambda:self.finish_compact_layout(mode))
    def finish_compact_layout(self,mode):
        if self.mode!=mode or self.pending_compact_mode!=mode or not self.w.isVisible(): return
        self.pending_compact_mode=None
        self.w.studio.fit_sidebar()
        self.layouts[mode]=encoded(self.w.saveState())
    def reset(self,all_modes=False):
        self.capture()
        self.w.timecode_overlay.set_locked(True)
        self.w.timecode_overlay.set_position([.5,1])
        if self.w.video_fullscreen: self.w.toggle_fullscreen()
        for mode in (('read','edit') if all_modes else (self.mode,)):
            self.profiles[mode]=dict(self.default_profiles[mode]); self.simple[mode]=mode=='read'; self.layouts.pop(mode,None); self.editable[mode]=False
        self.apply('read' if all_modes else self.mode); self.capture(); self.save()
    def configure(self):
        d=QDialog(self.w); d.setWindowTitle(tr('Options des modes Lecture / Édition'))
        root=QVBoxLayout(d); root.setContentsMargins(18,18,18,16); root.setSpacing(18); grid=QGridLayout(); grid.setHorizontalSpacing(28); grid.setVerticalSpacing(10); root.addLayout(grid); boxes={}
        names={'transport':'Commandes de lecture','timecode':'Time code','timeline':'Timeline','drawing':'Dessin','library':'Liste de lecture et médias','tools':'Barre d’outils'}
        self.capture()
        for col,(mode,title) in enumerate((('read','Lecture'),('edit','Édition')),1):
            grid.addWidget(QLabel(tr(title)),0,col,Qt.AlignmentFlag.AlignCenter)
            for row,key in enumerate(self.panels,1):
                if col==1: grid.addWidget(QLabel(tr(names.get(key,key))),row,0)
                box=QCheckBox(); box.setChecked(self.profiles[mode][key]); boxes[mode,key]=box; grid.addWidget(box,row,col,Qt.AlignmentFlag.AlignCenter)
            if col==1: grid.addWidget(QLabel(tr('Timeline allégée')),len(self.panels)+1,0)
            box=QCheckBox(); box.setChecked(self.simple[mode]); boxes[mode,'simple']=box; grid.addWidget(box,len(self.panels)+1,col,Qt.AlignmentFlag.AlignCenter)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(d.accept); buttons.rejected.connect(d.reject); root.addWidget(buttons)
        from dialogs import ButtonStyle
        d.button_style=ButtonStyle('Fusion'); d.button_style.setParent(d); buttons.setCenterButtons(True)
        for standard,title in [(QDialogButtonBox.StandardButton.Ok,'OK'),(QDialogButtonBox.StandardButton.Cancel,tr('Annuler'))]:
            button=buttons.button(standard); button.setText('&'+title); button.setStyle(d.button_style)
            shortcut=QShortcut(QKeySequence(title[0]),d); shortcut.setAutoRepeat(False); shortcut.activated.connect(button.click)
        if d.exec()==QDialog.DialogCode.Accepted:
            for mode in self.profiles:
                self.profiles[mode]={k:boxes[mode,k].isChecked() for k in self.panels}; self.simple[mode]=boxes[mode,'simple'].isChecked()
            self.apply(self.mode); self.save()
        d.deleteLater()
