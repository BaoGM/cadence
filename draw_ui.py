# SPDX-License-Identifier: GPL-3.0-only
from ui_text import tr
from dataclasses import replace
import math
from PySide6.QtCore import Qt,QObject,QEvent,QPointF,QRectF,QSignalBlocker,Signal,QSize
from PySide6.QtGui import QColor,QPainter,QPen,QConicalGradient,QLinearGradient,QTransform,QPointingDevice,QFont,QActionGroup,QPainterPath,QCursor
from PySide6.QtWidgets import QWidget, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox, QCheckBox, QPushButton, QDockWidget, QScrollArea, QLineEdit, QListWidget, QListWidgetItem, QInputDialog, QTabWidget, QAbstractItemView, QMenu, QToolButton, QButtonGroup
from widgets import ScrubDoubleSpinBox,ScrubSpinBox
from draw_selection import DrawSelection
from tool_icons import tool_icon
from drawing import Mark,DrawingKey,active_key,put_key,render_layer,VECTOR_TOOLS
from drag import ContinuousDrag
from shape_gesture import ShapeGesture
from draw_fonts import DrawingFontCombo

TOOL_SPECS=[('Curseur','cursor','Q'),('Pinceau','brush','B'),('Gomme','eraser','E'),('Lasso / déplacement','lasso','L'),('Texte','text','Shift+T'),('Pipette','picker','P'),('Flèche','arrow','A'),('Carré','rectangle','R'),('Cercle','ellipse','Shift+O')]

class ColorWheel(QWidget):
    changed=Signal(str)
    edited=Signal(str)
    editFinished=Signal()
    def __init__(self):
        super().__init__(); self.h=.04; self.s=.8; self.v=1.; self.drag=None
        self.setMinimumSize(180,180); self.setMaximumHeight(220); self.setToolTip(tr('Anneau : teinte · Carré : saturation et luminosité'))
    def geometry_parts(self):
        r=min(self.width(),self.height())/2-7; center=QPointF(self.width()/2,self.height()/2)
        return center,r,QRectF(center.x()-.48*r,center.y()-.48*r,.96*r,.96*r)
    def color(self): return QColor.fromHsvF(self.h,self.s,self.v).name()
    def set_color(self,text):
        color=QColor(text)
        if not color.isValid(): return False
        h,s,v,_=color.getHsvF(); self.h=h if h>=0 else self.h; self.s=s; self.v=v; self.update(); self.changed.emit(self.color()); return True
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing); center,r,square=self.geometry_parts()
        gradient=QConicalGradient(center,0)
        for i in range(7): gradient.setColorAt(i/6,QColor.fromHsvF((i/6)%1,1,1))
        p.setPen(QPen(gradient,r*.20)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawEllipse(center,r*.85,r*.85)
        gradient=QLinearGradient(square.topLeft(),square.topRight()); gradient.setColorAt(0,Qt.GlobalColor.white); gradient.setColorAt(1,QColor.fromHsvF(self.h,1,1)); p.fillRect(square,gradient)
        gradient=QLinearGradient(square.topLeft(),square.bottomLeft()); gradient.setColorAt(0,QColor(0,0,0,0)); gradient.setColorAt(1,Qt.GlobalColor.black); p.fillRect(square,gradient)
        p.setPen(QPen(Qt.GlobalColor.white,2)); p.setBrush(Qt.BrushStyle.NoBrush)
        a=self.h*math.tau; p.drawEllipse(center+QPointF(math.cos(a),-math.sin(a))*r*.85,4,4)
        p.drawEllipse(QPointF(square.left()+self.s*square.width(),square.top()+(1-self.v)*square.height()),4,4); p.end()
    def choose(self,pos):
        center,r,square=self.geometry_parts()
        if self.drag=='hue': self.h=(math.atan2(-(pos.y()-center.y()),pos.x()-center.x())/math.tau)%1
        else: self.s=max(0,min(1,(pos.x()-square.left())/square.width())); self.v=1-max(0,min(1,(pos.y()-square.top())/square.height()))
        self.changed.emit(self.color()); self.edited.emit(self.color()); self.update()
    def mousePressEvent(self,e):
        if e.button()!=Qt.MouseButton.LeftButton: return
        center,r,square=self.geometry_parts(); distance=math.hypot(e.position().x()-center.x(),e.position().y()-center.y())
        self.drag='sv' if square.contains(e.position()) else 'hue' if r*.7<distance<r else None
        if self.drag: self.choose(e.position())
    def mouseMoveEvent(self,e):
        if self.drag: self.choose(e.position())
    def mouseReleaseEvent(self,e):
        if self.drag:
            self.drag=None; self.editFinished.emit()

class DrawController(QObject):
    enabledChanged=Signal(bool)
    def __init__(self,window):
        super().__init__(window); self.win=window; self.viewer=window.viewer; self.enabled=False; self.stroke=None; self.tablet_down=False; self.cache=None; self.list_signature=None; self.selection=DrawSelection(self); self.text_drag=None; self.tool_buttons={}; self.tool_actions={}
        from drawing_cache import DrawingRasterCache
        self.raster_cache=DrawingRasterCache()
        self.panel=QDockWidget(tr('Draw over'),window); self.panel.setObjectName('draw_over'); self.panel.setMinimumWidth(200)
        content=QWidget(); col=QVBoxLayout(content); col.setContentsMargins(14,12,14,12)
        def title(text): col.addWidget(QLabel(tr(text)))
        self.size_drag=None; self.shape_drag=None; self.sampling=False; self.temporary_picker=False; self.last_tool='brush'
        self.visible=QCheckBox(tr('Afficher le calque de dessins')); self.visible.setChecked(True); self.visible.toggled.connect(self.invalidate); col.addWidget(self.visible)
        self.export=QCheckBox(tr('Inclure les dessins à l’export')); self.export.setChecked(True); col.addWidget(self.export)
        outer=col; tabs=QTabWidget(); outer.addWidget(tabs)
        tools_page=QWidget(); keys_page=QWidget()
        tabs.addTab(tools_page,tr('Outils')); tabs.addTab(keys_page,tr('Clés'))
        col=QVBoxLayout(tools_page); col.setContentsMargins(4,8,4,4)
        self.tool=QComboBox()
        for text,value,key in TOOL_SPECS: self.tool.addItem(tr(text),value)
        self.tool.currentIndexChanged.connect(self.tool_changed); self.tool.hide()
        toolrow=QGridLayout(); self.tool_group=QButtonGroup(self); self.tool_group.setExclusive(True)
        for i,(tool_title,name,key) in enumerate(TOOL_SPECS):
            tip=tool_title+' · '+key.replace('Shift','Maj')
            b=QToolButton(); b.setIcon(tool_icon(name)); b.setIconSize(QSize(26,26)); b.setFixedSize(44,40); b.setCheckable(True); b.setChecked(name=='cursor'); b.setToolTip(tr(tip)); b.setAccessibleName(tr(tool_title)); b.clicked.connect(lambda checked=False,t=name:self.choose_tool(t)); self.tool_group.addButton(b); toolrow.addWidget(b,i//3,i%3); self.tool_buttons[name]=b
        toolrow.setAlignment(Qt.AlignmentFlag.AlignHCenter); col.addLayout(toolrow)
        tool_separator=QFrame(); tool_separator.setObjectName('drawing_tool_separator'); tool_separator.setFrameShape(QFrame.Shape.HLine); tool_separator.setStyleSheet('color:#354354;'); col.addWidget(tool_separator)
        self.text_controls=QWidget(); textcol=QVBoxLayout(self.text_controls); textcol.setContentsMargins(0,0,0,0)
        self.font_combo=DrawingFontCombo(); self.font_combo.currentFontChanged.connect(self.text_style_changed); textcol.addWidget(self.font_combo)
        stylerow=QHBoxLayout(); self.style_buttons={}
        for name,label,tip in [('bold','G','Gras'),('italic','I','Italique'),('underline','S','Souligné'),('strikeout','abc','Barré')]:
            b=QToolButton(); b.setText(tr(label)); b.setToolTip(tr(tip)); b.setAccessibleName(tr(tip)); b.setCheckable(True); b.setMinimumSize(32,28); font=QFont('Arial'); getattr(font,{'bold':'setBold','italic':'setItalic','underline':'setUnderline','strikeout':'setStrikeOut'}[name])(True); b.setFont(font); b.toggled.connect(self.text_style_changed); stylerow.addWidget(b); self.style_buttons[name]=b
        textcol.addLayout(stylerow); hint=QLabel(tr('Glisser pour tracer une zone. Le texte s’ajuste à sa taille. Tirer un coin pour redimensionner ; double-clic pour éditer.')); hint.setWordWrap(True); textcol.addWidget(hint); col.addWidget(self.text_controls); self.text_controls.hide()
        self.size=ScrubDoubleSpinBox(); self.size.setRange(.5,400); self.size.setValue(8); self.size.setSuffix(tr(' px')); self.size.setSingleStep(1)
        self.opacity=ScrubDoubleSpinBox(); self.opacity.setRange(1,100); self.opacity.setValue(100); self.opacity.setSuffix(tr(' %')); self.opacity.setSingleStep(5); self.opacity.valueChanged.connect(self.change_selection_opacity); self.opacity.editingFinished.connect(self.finish_opacity_edit)
        self.sensitivity=ScrubDoubleSpinBox(); self.sensitivity.setRange(.1,5); self.sensitivity.setValue(1); self.sensitivity.setSingleStep(.1); self.sensitivity.setDecimals(2)
        self.sensitivity.setToolTip(tr('Exposant de la courbe : 1 = linéaire ; inférieur à 1 = plus sensible ; supérieur à 1 = pression plus ferme.'))
        values=QGridLayout(); values.setColumnStretch(1,1)
        for row,(text,widget) in enumerate([('Taille',self.size),('Opacité',self.opacity),('Sensibilité',self.sensitivity)]):
            values.addWidget(QLabel(tr(text)),row,0); values.addWidget(widget,row,1)
        col.addLayout(values)
        self.wheel=ColorWheel(); col.addWidget(self.wheel); self.hex=QLineEdit(self.wheel.color()); self.hex.setMaxLength(7); self.hex.setPlaceholderText(tr('#RRGGBB')); col.addWidget(self.hex)
        self.wheel.changed.connect(self.hex.setText); self.wheel.edited.connect(self.recolor_selection); self.wheel.editFinished.connect(self.finish_color_edit); self.hex.editingFinished.connect(self.read_color)
        tools_col=col; col=QVBoxLayout(keys_page); col.setContentsMargins(4,8,4,4)
        row=QHBoxLayout()
        for text,fn in [('Dupliquer la clé au curseur',self.copy_key)]:
            b=QPushButton(tr(text)); b.clicked.connect(fn); row.addWidget(b)
        col.addLayout(row)
        self.scope=QLabel(); self.scope.setWordWrap(True); col.addWidget(self.scope)
        self.keys=QListWidget(); self.keys.setMinimumHeight(150); self.keys.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection); self.keys.itemClicked.connect(self.key_clicked); self.keys.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); self.keys.customContextMenuRequested.connect(self.keys_context); col.addWidget(self.keys)
        row=QHBoxLayout()
        for text,fn in [('Supprimer la sélection',self.delete_key)]:
            b=QPushButton(tr(text)); b.clicked.connect(fn); row.addWidget(b)
        col.addLayout(row)
        col.addStretch()
        col=tools_col
        separator=QFrame(); separator.setFrameShape(QFrame.Shape.HLine); separator.setStyleSheet('color:#354354;'); col.addWidget(separator)
        onion_values=QGridLayout(); onion_values.setColumnStretch(1,1)
        self.onion=QCheckBox(tr('Activer la pelure d’oignon')); col.addWidget(self.onion); self.onion.toggled.connect(self.invalidate)
        self.before=ScrubSpinBox(); self.after=ScrubSpinBox()
        # The controls describe the display range around each source drawing.
        for row,(text,widget) in enumerate([('Images précédentes',self.after),('Images suivantes',self.before)]):
            widget.setRange(0,300); widget.setValue(3); onion_values.addWidget(QLabel(tr(text)),row,0); onion_values.addWidget(widget,row,1); widget.setToolTip(tr('Portée continue en images vidéo ; 0 désactive ce sens.')); widget.valueChanged.connect(self.invalidate)
        self.ghost=ScrubSpinBox(); self.ghost.setRange(1,100); self.ghost.setValue(100); self.ghost.setSuffix(tr(' %')); self.ghost.valueChanged.connect(self.invalidate); onion_values.addWidget(QLabel(tr('Opacité')),2,0); onion_values.addWidget(self.ghost,2,1); col.addLayout(onion_values); col.addStretch()
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(content); self.panel.setWidget(scroll)
        window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,self.panel); self.panel.hide()
        self.viewer.installEventFilter(self); self.viewer.draw_controller=self
    def menus(self):
        w=self.win; menu=w.menuBar().addMenu(tr('Dessin'))
        self.visibility_action=w.action(menu,'Afficher le calque de dessins',lambda checked:self.visible.setChecked(checked)); self.visibility_action.setCheckable(True); self.visibility_action.setChecked(self.visible.isChecked())
        self.visible.toggled.connect(self.visibility_action.setChecked)
        view=next(a.menu() for a in w.menuBar().actions() if a.text()==tr('Affichage'))
        self.panel_action=w.action(view,'Afficher les outils de dessin',lambda checked:w.set_panel('drawing',checked),'Ctrl+Shift+D'); self.panel_action.setCheckable(True); w.panel_actions['drawing']=self.panel_action
        tools=w.menuBar().addMenu(tr('Outils')); self.tools_menu=tools; self.action_group=QActionGroup(w); self.action_group.setExclusive(True)
        for title,tool,key in TOOL_SPECS:
            action=w.action(tools,title,lambda checked=False,t=tool:self.choose_tool(t),key); action.setIcon(tool_icon(tool)); action.setCheckable(True); action.setChecked(tool=='cursor'); self.action_group.addAction(tr(action)); self.tool_actions[tool]=action
        menu.addSeparator(); w.action(menu,'Ajouter un marqueur',self.add_marker,'S'); w.action(menu,'Dupliquer la clé au curseur',self.copy_key,'Shift+K')
        self.clipboard_actions={}
        for operation,title,shortcut in [('copy','Copier les clés','C'),('cut','Couper les clés','X'),('paste','Coller les clés','V')]:
            self.clipboard_actions[operation]=w.action(menu,title,lambda checked=False,op=operation:self.edit_clipboard(op),shortcut)
        w.timeline.drawing_actions=self.clipboard_actions
        w.timeline.drawingClipboardRequested.connect(lambda op,a,b:self.edit_clipboard(op,a,b))
        w.action(menu,'Supprimer les clés',self.delete_selected_keys,'D')
        w.action(menu,'Supprimer les marqueurs',self.delete_markers)
        w.timeline.markerAdded.connect(self.add_marker)
        w.timeline.markersDeleted.connect(self.delete_markers)
    def navigate(self,sign):
        if self.win.editing_text() or self.win.job: return
        starts=[k.start for k in self.win.doc.state.drawings if k.start<self.win.doc.state.length]
        starts=sorted(set(starts)|set(self.win.doc.state.frame_markers))
        if not starts: return
        pos=self.win.doc.state.position; choices=[start for start in starts if (start-pos)*sign>0]
        self.win.seek((min(choices) if sign>0 else max(choices)) if choices else (min(starts) if sign>0 else max(starts)),audition=True)
    def add_marker(self,frame=None):
        w=self.win
        if w.editing_text() or w.job or not w.doc.state.length: return
        w.pause(); self.finish(); st=w.doc.state
        frame=min(st.position,st.length-1) if frame is None or isinstance(frame,bool) else frame
        if not 0<=frame<st.length: return
        if w.doc.commit('Supprimer le marqueur' if frame in st.frame_markers else 'Ajouter un marqueur',replace(st,frame_markers=tuple(sorted(set(st.frame_markers)^{frame})))): w.refresh(); w.request_frame()
    def delete_markers(self,a=None,b=None):
        w=self.win
        if w.editing_text() or w.job: return
        st=w.doc.state
        if a is None or isinstance(a,bool): a,b=st.selection or (st.position,st.position+1)
        if w.doc.commit('Supprimer les marqueurs',replace(st,frame_markers=tuple(f for f in st.frame_markers if not a<=f<b))): w.refresh(); w.request_frame()
    def blank_key(self):
        if self.win.editing_text() or self.win.job: return
        self.win.pause(); self.finish(); st=self.win.doc.state; a,b=st.selection or (st.position,st.position+1)
        self.commit_key(DrawingKey(a,b),'Ajouter une clé de dessin vide')
    def text_style(self):
        return dict(font_family=self.font_combo.currentFont().family(),**{name:button.isChecked() for name,button in self.style_buttons.items()})
    def read_text_style(self,mark):
        with QSignalBlocker(self.font_combo): self.font_combo.setCurrentFont(QFont(mark.font_family))
        for name,button in self.style_buttons.items():
            with QSignalBlocker(button): button.setChecked(getattr(mark,name))
    def select_text(self,index,key):
        self.selection.indices=(index,); self.selection.key_start=key.start; self.selection.source=self.win.doc.state.drawings; self.selection.key=key; self.invalidate()
    def text_style_changed(self,*args):
        if not hasattr(self,'style_buttons') or self.tool.currentData()!='text': return
        st=self.win.doc.state; key=active_key(st.drawings,st.position); indices=self.selection.indices
        if not key or not indices or self.selection.source is not st.drawings: return
        marks=tuple(replace(m,**self.text_style()) if i in indices and m.tool=='text' else m for i,m in enumerate(key.marks))
        if marks!=key.marks:
            updated=replace(key,marks=marks); self.commit_key(updated,'Modifier le style du texte'); self.select_text(indices[0],updated)
    def pending_text_rect(self):
        a=self.text_drag['anchor']; b=self.text_drag['end']
        if abs(a[0]-b[0])+abs(a[1]-b[1])<.01: return QRectF(a[0],a[1],max(.005,min(.4,1-a[0])),max(.005,min(.16,1-a[1])))
        return QRectF(min(a[0],b[0]),min(a[1],b[1]),max(.005,abs(a[0]-b[0])),max(.005,abs(a[1]-b[1])))
    def finish_text_box(self):
        if not self.text_drag: return
        data=self.text_drag; rect=self.pending_text_rect(); self.text_drag=None; self.invalidate()
        if data['source'] is not self.win.doc.state.drawings: return
        text,ok=QInputDialog.getMultiLineText(self.win,tr('Texte'),tr('Texte à ajouter dans la zone :'))
        if ok and text.strip():
            mark=replace(data['mark'],text=text[:10000],points=((rect.x(),rect.y(),1.),),box=(rect.width(),rect.height()),**self.text_style())
            key=replace(data['key'],marks=data['key'].marks+(mark,)); self.commit_key(key,'Ajouter une zone de texte'); self.select_text(len(key.marks)-1,key)
    def edit_text(self,pos):
        if self.tool.currentData()!='text': return
        self.text_drag=None; self.selection.gesture=None; self.selection.preview=None
        point=self.point(pos)
        if point is None or not self.selection.begin(point,'text'): return
        self.selection.gesture=None; self.selection.preview=None; key=self.selection.key; index=self.selection.indices[0]; mark=key.marks[index]; self.read_text_style(mark)
        text,ok=QInputDialog.getMultiLineText(self.win,tr('Modifier le texte'),tr('Texte :'),mark.text)
        if ok:
            marks=tuple(replace(m,text=text[:10000]) if i==index else m for i,m in enumerate(key.marks)); updated=replace(key,marks=marks)
            self.commit_key(updated,'Modifier le texte'); self.select_text(index,updated)
    def read_color(self):
        if not self.wheel.set_color(self.hex.text()): self.hex.setText(tr(self.wheel.color()))
        else: self.recolor_selection(self.wheel.color())
    def recolor_selection(self,color):
        if self.win.job: return
        self.selection.sync(); st=self.win.doc.state; key=active_key(st.drawings,st.position)
        indices=self.selection.indices
        if not key or not indices: return
        def recolor(mark):
            if mark.tool=='eraser': return mark
            return replace(mark,color=color,children=tuple(recolor(child) for child in mark.children))
        marks=tuple(recolor(mark) if i in indices else mark for i,mark in enumerate(key.marks))
        self.selection.preview=replace(key,marks=marks); self.color_edit=True; self.invalidate()
        if not self.wheel.drag: self.finish_color_edit()
    def finish_color_edit(self):
        if not getattr(self,'color_edit',False): return
        self.color_edit=False; self.selection.sync()
        key=self.selection.preview; indices=self.selection.indices; self.selection.preview=None
        if key and indices:
            self.commit_key(key,'Changer la couleur des dessins')
            self.selection.indices=indices; self.selection.key_start=key.start; self.selection.key=key; self.selection.source=self.win.doc.state.drawings
        self.invalidate()
    def change_selection_opacity(self,value):
        if self.win.job: return
        self.selection.sync(); st=self.win.doc.state; key=active_key(st.drawings,st.position)
        indices=self.selection.indices
        if not key or not indices: return
        marks=tuple(replace(mark,opacity=value/100) if i in indices and mark.tool!='eraser' else mark for i,mark in enumerate(key.marks))
        self.selection.preview=replace(key,marks=marks); self.opacity_edit=True; self.invalidate()
        if not self.opacity.scrubbing: self.finish_opacity_edit()
    def finish_opacity_edit(self):
        if not getattr(self,'opacity_edit',False): return
        self.opacity_edit=False; self.selection.sync()
        key=self.selection.preview; indices=self.selection.indices; self.selection.preview=None
        if key and indices:
            self.commit_key(key,'Changer l’opacité des dessins')
            self.selection.indices=indices; self.selection.key_start=key.start; self.selection.key=key; self.selection.source=self.win.doc.state.drawings
        self.invalidate()
    def tool_changed(self):
        self.finish(); self.selection.clear()
        name=self.tool.currentData(); self.text_controls.setVisible(name=='text')
        self.enabled=name!='cursor'
        if self.enabled:
            self.last_tool=name; self.win.pause()
            if name!='picker': self.visible.setChecked(True); self.ensure_drawing_frame()
        self.enabledChanged.emit(self.enabled)
        self.viewer.setCursor(Qt.CursorShape.CrossCursor if self.enabled else Qt.CursorShape.OpenHandCursor)
        for tool,b in self.tool_buttons.items():
            with QSignalBlocker(b): b.setChecked(tool==name)
        for tool,a in self.tool_actions.items():
            with QSignalBlocker(a): a.setChecked(tool==name)
        self.invalidate()
    def picker_available(self,modifiers):
        return (self.enabled and self.viewer.loaded and not self.win.job
                and self.tool.currentData() in ('brush','eraser','arrow','rectangle','ellipse','text')
                and modifiers==Qt.KeyboardModifier.ControlModifier
                and not (self.stroke or self.shape_drag or self.text_drag or self.size_drag or self.selection.gesture or self.viewer.nav))
    def update_picker_cursor(self,modifiers):
        active=self.picker_available(modifiers)
        if active==self.temporary_picker: return
        self.temporary_picker=active
        if active:
            if not hasattr(self,'picker_cursor'): self.picker_cursor=QCursor(tool_icon('picker').pixmap(32,32),5,27)
            self.viewer.setCursor(self.picker_cursor)
        else:
            self.viewer.setCursor(Qt.CursorShape.CrossCursor if self.enabled else Qt.CursorShape.OpenHandCursor)
    def ensure_drawing_frame(self):
        st=self.win.doc.state
        if st.selection and not st.selection[0]<=st.position<st.selection[1]: self.win.seek(max(st.selection[0],min(st.position,st.selection[1]-1)))
    def choose_tool(self,tool):
        index=self.tool.findData(tool)
        if index<0: return
        if index==self.tool.currentIndex(): self.tool_changed()
        else: self.tool.setCurrentIndex(index)
    def set_enabled(self,enabled):
        self.choose_tool(self.last_tool if enabled else 'cursor')
    def delete_selected_keys(self):
        if self.win.editing_text() or self.win.job: return
        st=self.win.doc.state; key=active_key(st.drawings,st.position)
        span=st.selection or ((key.start,key.end) if key else None)
        if span: self.win.edit_drawing_timeline('delete',*span)
    def invalidate(self,*args): self.cache=None; self.viewer.update()
    def refresh(self):
        st=self.win.doc.state
        if not st.drawings: self.raster_cache.clear(); self.cache=None
        self.selection.sync()
        if self.stroke and (st.position!=self.stroke_frame or st.drawings is not self.stroke_keys): self.cancel()
        selection=st.selection
        self.scope.setText(tr(f'Plage active : {selection[0]} → {selection[1]-1}' if selection else f'Image courante : {st.position}'))
        source=getattr(self,'list_source',None)
        signature=self.list_signature if source is st.drawings else tuple((k.start,k.end,len(k.marks)) for k in st.drawings)
        self.list_source=st.drawings
        if signature!=self.list_signature:
            selected={item.data(Qt.ItemDataRole.UserRole) for item in self.keys.selectedItems()}
            self.keys.clear()
            for k in st.drawings:
                item=QListWidgetItem(tr(f'◆ {k.start}'+(f' → {k.end-1}' if k.end>k.start+1 else '')+f' · {len(k.marks)} éléments')); item.setData(Qt.ItemDataRole.UserRole,k.start); self.keys.addItem(tr(item)); item.setSelected(k.start in selected)
            self.list_signature=signature
        self.viewer.update()
    def target(self):
        st=self.win.doc.state; key=active_key(st.drawings,st.position)
        if st.selection: a,b=st.selection
        elif key: a,b=key.start,key.end
        else: a,b=st.position,st.position+1
        return DrawingKey(a,b,key.marks if key else ())
    def commit_key(self,key,label):
        if self.win.job or not 0<=key.start<key.end<=self.win.doc.state.length: return
        self.win.pause(); self.win.commit_exposure(); st=self.win.doc.state
        self.win.doc.commit(label,replace(st,drawings=put_key(st.drawings,key))); self.invalidate(); self.win.refresh()
    def copy_key(self):
        if self.win.editing_text(): return
        st=self.win.doc.state; key=active_key(st.drawings,st.position) or next((k for k in reversed(st.drawings) if k.start<st.position),None)
        if key:
            a,b=st.selection or (st.position,st.position+1); self.commit_key(DrawingKey(a,b,key.marks),'Copier une clé de dessin')
    def selected_objects(self):
        self.selection.sync()
        return self.selection.indices
    def edit_objects(self,operation):
        if self.win.job or self.win.editing_text(): return False
        indices=self.selected_objects(); st=self.win.doc.state; key=active_key(st.drawings,st.position)
        if operation=='paste':
            marks=getattr(self,'object_clipboard',())
            if not marks or not st.length: return False
            key=key or self.target(); start=len(key.marks); updated=replace(key,marks=key.marks+marks)
            self.commit_key(updated,'Coller les objets'); indices=tuple(range(start,len(updated.marks)))
            self.selection.indices=indices; self.selection.source=self.win.doc.state.drawings; self.selection.key_start=updated.start
            self.invalidate(); return True
        if not indices or not key: return False
        if operation in ('copy','cut'):
            from drawing import move_erased_selection
            grouped,chosen=move_erased_selection(key.marks,indices,0,0)
            self.object_clipboard=tuple(grouped[i] for i in chosen)
        if operation in ('delete','cut'):
            remaining=tuple(m for i,m in enumerate(key.marks) if i not in indices)
            label='Supprimer les objets' if operation=='delete' else 'Couper les objets'
            if any(m.tool!='eraser' for m in remaining): self.commit_key(replace(key,marks=remaining),label)
            else:
                self.win.pause(); self.win.commit_exposure()
                current=self.win.doc.state
                self.win.doc.commit(label,replace(current,drawings=tuple(k for k in current.drawings if k is not key)))
                self.win.refresh()
            self.selection.clear(); self.invalidate()
        return True
    def objects_menu(self,point):
        if not self.enabled or self.tool.currentData()!='lasso': return None
        indices=self.selected_objects(); pos=self.point(point)
        if indices and (pos is None or not self.selection.bounds().adjusted(-.006,-.006,.006,.006).contains(QPointF(*pos))): return None
        if not indices and not getattr(self,'object_clipboard',()): return None
        menu=QMenu(self.viewer)
        for operation,title in [('paste','Coller'),('copy','Copier'),('cut','Couper'),('delete','Supprimer')]:
            if operation=='delete': menu.addSeparator()
            action=menu.addAction(tr(title)); action.setEnabled(bool(getattr(self,'object_clipboard',())) if operation=='paste' else bool(indices))
            action.triggered.connect(lambda checked=False,op=operation:self.edit_objects(op))
        return menu
    def clipboard_span(self):
        st=self.win.doc.state; key=active_key(st.drawings,st.position)
        return st.selection or ((key.start,key.end) if key else None)
    def edit_clipboard(self,operation,start=None,end=None):
        w=self.win
        if w.editing_text() or w.job: return False
        w.pause(); self.finish(); w.commit_exposure()
        if operation=='paste':
            changed=w.doc.paste_drawings(w.doc.state.position if start is None else start)
        else:
            span=self.clipboard_span() if start is None else (start,end)
            if not span: return False
            changed=(w.doc.copy_drawings if operation=='copy' else w.doc.cut_drawings)(*span)
        if changed:
            w.clipboard_kind='drawing'; w.timeline.selection_track='drawing'; self.invalidate(); w.refresh()
            if operation!='copy': w.request_frame()
        return changed
    def expose_selection(self):
        st=self.win.doc.state; key=active_key(st.drawings,st.position)
        if key and st.selection: self.commit_key(DrawingKey(*st.selection,key.marks),'Étendre le dessin à la sélection')
    def key_clicked(self,item):
        self.win.timeline.selection_track='drawing'; self.win.seek(item.data(Qt.ItemDataRole.UserRole))
    def keys_context(self,point):
        item=self.keys.itemAt(point)
        if not item: return
        if not item.isSelected(): self.keys.clearSelection(); item.setSelected(True)
        menu=QMenu(tr(self.keys)); menu.addAction(tr('Supprimer'),self.delete_key); menu.exec(self.keys.mapToGlobal(point))
    def delete_key(self):
        if self.win.job: return
        self.win.pause(); st=self.win.doc.state; starts={item.data(Qt.ItemDataRole.UserRole) for item in self.keys.selectedItems()}
        if not starts:
            key=active_key(st.drawings,st.position)
            if key: starts={key.start}
        if starts:
            self.win.doc.commit('Supprimer les clés de dessin',replace(st,drawings=tuple(k for k in st.drawings if k.start not in starts))); self.invalidate(); self.win.refresh()
    def a_rect(self,size):
        v=self.viewer; width,height=size.width(),size.height(); x,y=-width/2,-height/2
        if v.comparing:
            if v.compare_mode=='front' and v.compare_swapped: return None
            if v.compare_mode=='horizontal': width/=2; x+=width if v.compare_swapped else 0
            elif v.compare_mode=='vertical': height/=2; y+=height if v.compare_swapped else 0
        return QRectF(x,y,width,height)
    def point(self,pos,allow_outside=False):
        v=self.viewer
        if v.image is None or v.rgb is None: return None
        size=v.image_size().scaled(v.size(),Qt.AspectRatioMode.KeepAspectRatio); rect=self.a_rect(size)
        if rect is None: return None
        transform=QTransform(); transform.translate(v.width()/2+v.pan.x(),v.height()/2+v.pan.y()); transform.rotate(v.angle); transform.scale(v.zoom,v.zoom)
        point=transform.inverted()[0].map(pos)
        if not allow_outside and not rect.contains(point): return None
        if not allow_outside and v.comparing and v.compare_mode=='wipe' and v.reference_rgb is not None:
            from wipe import working_area
            if not working_area(rect,v.wipe_position,v.compare_swapped).contains(point): return None
        x=(point.x()-rect.x())/rect.width(); y=(point.y()-rect.y())/rect.height()
        if v.flip_h: x=1-x
        if v.flip_v: y=1-y
        return max(-4,min(5,x)),max(-4,min(5,y))
    def begin(self,pos,pressure,eraser=False,modifiers=Qt.KeyboardModifier.NoModifier):
        if self.win.job or self.tool.currentData()=='cursor': return
        self.ensure_drawing_frame()
        self.win.pause(); self.win.commit_exposure(); self.win.refresh()
        if self.win.doc.state.position>=self.win.doc.state.length: return
        point=self.point(pos)
        if point is None: return
        self.viewer.setFocus(); tool='eraser' if eraser else self.tool.currentData()
        if self.selection.begin(point,tool,force_move=bool(modifiers&Qt.KeyboardModifier.AltModifier)):
            if tool=='text' and self.selection.indices: self.read_text_style(self.selection.key.marks[self.selection.indices[0]])
            self.invalidate(); return
        reference=next(iter(self.win.doc.media.values()),{}); height=max(1,reference.get('height',720))
        mark=Mark(tool,(point+(pressure,),),self.size.value()/height,self.wheel.color(),self.opacity.value()/100,True,self.sensitivity.value())
        width,height=self.viewer.rgb.shape[1],self.viewer.rgb.shape[0]
        if tool in VECTOR_TOOLS:
            mark=replace(mark,points=(point+(1.,),point+(1.,)),pressure=False)
            self.shape_drag=ShapeGesture(tool,(point[0]*width,point[1]*height))
            self.shape_drag.update(self.shape_drag.last,ctrl=bool(modifiers&Qt.KeyboardModifier.ControlModifier),alt=bool(modifiers&Qt.KeyboardModifier.AltModifier))
        key=self.target()
        if tool=='text':
            self.text_drag=dict(anchor=point,end=point,key=key,mark=mark,source=self.win.doc.state.drawings,gesture=ShapeGesture('rectangle',(point[0]*width,point[1]*height))); self.invalidate(); return
        self.stroke=mark; self.stroke_key=key; self.stroke_frame=self.win.doc.state.position; self.stroke_keys=self.win.doc.state.drawings; self.invalidate()
    def move(self,pos,pressure,modifiers=Qt.KeyboardModifier.NoModifier):
        alt=bool(modifiers&Qt.KeyboardModifier.AltModifier)
        if self.text_drag:
            point=self.point(pos,True)
            if point:
                width,height=self.viewer.rgb.shape[1],self.viewer.rgb.shape[0]
                gesture=self.text_drag['gesture']; gesture.update((point[0]*width,point[1]*height),alt=alt)
                a,b=gesture.normalized(width,height); self.text_drag.update(anchor=a[:2],end=b[:2]); self.invalidate()
            return
        if self.selection.gesture:
            point=self.point(pos,True)
            if point is not None: self.selection.move(point,alt=alt)
            return
        if not self.stroke: return
        point=self.point(pos,True)
        if point is None: return
        if self.stroke.tool in VECTOR_TOOLS:
            width,height=self.viewer.rgb.shape[1],self.viewer.rgb.shape[0]
            gesture=self.shape_drag; gesture.update((point[0]*width,point[1]*height),shift=bool(modifiers&Qt.KeyboardModifier.ShiftModifier),ctrl=bool(modifiers&Qt.KeyboardModifier.ControlModifier),alt=alt)
            self.stroke=replace(self.stroke,points=gesture.normalized(width,height),angle=gesture.angle); self.invalidate(); return
        old=self.stroke.points[-1]
        if math.hypot(point[0]-old[0],point[1]-old[1])<.0003 and abs(pressure-old[2])<.01: return
        self.stroke=replace(self.stroke,points=self.stroke.points+(point+(pressure,),)); self.invalidate()
    def finish(self):
        self.finish_size_drag()
        self.finish_text_box()
        self.selection.finish()
        if self.stroke:
            mark=self.stroke; key=self.stroke_key; self.stroke=None
            if mark.tool not in VECTOR_TOOLS or mark.points[0][:2]!=mark.points[-1][:2]:
                self.commit_key(replace(key,marks=key.marks+(mark,)),'Gommer le dessin' if mark.tool=='eraser' else 'Dessiner une forme' if mark.tool in VECTOR_TOOLS else 'Dessiner un trait')
        self.tablet_down=False
        self.shape_drag=None
    def finish_size_drag(self,restore=True):
        if self.size_drag:
            self.size_drag.finish(restore=restore); self.size_drag=None
            self.viewer.setCursor(Qt.CursorShape.CrossCursor if self.enabled else Qt.CursorShape.OpenHandCursor)
            self.viewer.update()
    def cancel(self):
        if self.size_drag: self.size.setValue(self.size_base)
        self.finish_size_drag(); self.text_drag=None; self.shape_drag=None; self.selection.clear(); self.stroke=None; self.tablet_down=False; self.invalidate()
    def eventFilter(self,obj,e):
        if not self.enabled or not self.viewer.loaded: return False
        kind=e.type()
        pointer_press=kind in (QEvent.Type.MouseButtonPress,QEvent.Type.MouseButtonDblClick,QEvent.Type.TabletPress) and e.button()==Qt.MouseButton.LeftButton
        if pointer_press and (self.tool.currentData()=='picker' or self.picker_available(e.modifiers())):
            self.update_picker_cursor(e.modifiers())
            self.finish(); self.win.pause(); self.sampling=True; self.sample(e.position()); e.accept(); return True
        if getattr(self,'sampling',False):
            if kind in (QEvent.Type.MouseMove,QEvent.Type.TabletMove): self.sample(e.position()); e.accept(); return True
            if kind in (QEvent.Type.MouseButtonRelease,QEvent.Type.TabletRelease): self.sampling=False; e.accept(); return True
            if kind in (QEvent.Type.Hide,QEvent.Type.WindowDeactivate): self.sampling=False
        if kind in (QEvent.Type.KeyPress,QEvent.Type.KeyRelease) and e.key() in (Qt.Key.Key_Shift,Qt.Key.Key_Control,Qt.Key.Key_Alt) and (self.shape_drag or self.text_drag):
            flag={Qt.Key.Key_Shift:Qt.KeyboardModifier.ShiftModifier,Qt.Key.Key_Control:Qt.KeyboardModifier.ControlModifier,Qt.Key.Key_Alt:Qt.KeyboardModifier.AltModifier}[e.key()]
            mods=(e.modifiers()|flag) if kind==QEvent.Type.KeyPress else (e.modifiers()&~flag)
            # Re-evaluate constraints without needing another mouse movement.
            if hasattr(self,'gesture_pos'): self.move(self.gesture_pos,1.,mods)
            e.accept(); return True
        if self.size_drag:
            if kind in (QEvent.Type.MouseMove,QEvent.Type.TabletMove):
                dx=self.size_drag.move(e.globalPosition()).x(); self.size.setValue(self.size_base+dx*.5); self.viewer.update(); e.accept(); return True
            if kind in (QEvent.Type.MouseButtonRelease,QEvent.Type.TabletRelease): self.finish_size_drag(); e.accept(); return True
            if kind==QEvent.Type.KeyPress and e.key()==Qt.Key.Key_Escape:
                self.size.setValue(self.size_base); self.finish_size_drag(); e.accept(); return True
        if kind in (QEvent.Type.MouseButtonPress,QEvent.Type.TabletPress) and e.button()==Qt.MouseButton.LeftButton and e.modifiers()&Qt.KeyboardModifier.ShiftModifier and self.tool.currentData() in ('brush','eraser')+VECTOR_TOOLS:
            self.finish(); self.size_base=self.size.value(); self.size_drag=ContinuousDrag(e.globalPosition()); self.size_point=self.point(e.position(),True); self.viewer.setCursor(Qt.CursorShape.SizeHorCursor); self.viewer.update(); e.accept(); return True
        if kind==QEvent.Type.KeyPress and e.key()==Qt.Key.Key_Escape and (self.text_drag or self.stroke or self.selection.indices or self.selection.gesture): self.cancel(); return True
        if kind in (QEvent.Type.TabletPress,QEvent.Type.TabletMove,QEvent.Type.TabletRelease):
            pressure=max(0,min(1,e.pressure()))
            if kind==QEvent.Type.TabletPress:
                self.tablet_down=True; self.gesture_pos=e.position(); self.begin(e.position(),pressure,e.pointerType()==QPointingDevice.PointerType.Eraser,e.modifiers())
            elif kind==QEvent.Type.TabletMove and self.tablet_down: self.gesture_pos=e.position(); self.move(e.position(),pressure,e.modifiers())
            elif kind==QEvent.Type.TabletRelease: self.finish()
            e.accept(); return True
        if kind==QEvent.Type.MouseButtonPress and e.button()==Qt.MouseButton.LeftButton:
            self.gesture_pos=e.position(); self.begin(e.position(),1.,modifiers=e.modifiers()); e.accept(); return True
        if kind==QEvent.Type.MouseMove and (self.text_drag or self.stroke or self.selection.gesture):
            self.gesture_pos=e.position(); self.move(e.position(),1.,e.modifiers()); e.accept(); return True
        if kind==QEvent.Type.MouseButtonRelease and e.button()==Qt.MouseButton.LeftButton:
            self.finish(); e.accept(); return True
        if kind==QEvent.Type.MouseButtonDblClick and e.button()==Qt.MouseButton.LeftButton:
            self.edit_text(e.position()); e.accept(); return True
        if kind in (QEvent.Type.Hide,QEvent.Type.WindowDeactivate): self.finish()
        return False
    def sample(self,point):
        color=self.viewer.sample_color(point)
        if color is not None: self.wheel.set_color(color)
    def paint(self,painter,size,adornments=True,layer_draw=None,accelerated=False):
        v=self.viewer
        if not self.visible.isChecked() or v.rgb is None: return
        rect=self.a_rect(size)
        if rect is None: return
        st=self.win.doc.state; keys=st.drawings; frame=st.position
        if self.selection.preview: keys=put_key(keys,self.selection.preview)
        if self.stroke: keys=put_key(keys,replace(self.stroke_key,marks=self.stroke_key.marks+(self.stroke,)))
        before=after=0
        if self.onion.isChecked() and self.ghost.value()>0:
            before=self.before.value(); after=self.after.value()
        from drawing import nearby_keys
        nearby=tuple(key for key in nearby_keys(keys,frame,before,after) if key.marks)
        active=active_key(keys,frame)
        phase=frame if any(key is not active for key in nearby) else None
        width,height=v.rgb.shape[1],v.rgb.shape[0]; signature=(id(st.drawings),id(active),phase,id(self.stroke),width,height,before,after,self.ghost.value(),st.flip_h,st.flip_v)
        if accelerated:
            from drawing_gpu import paint_layers
            self.raster_cache.retain(keys)
            paint_layers(painter,rect,keys,frame,width,height,before,after,self.ghost.value()/100,self.raster_cache,v.flip_h,v.flip_v,layer_draw)
        elif not nearby:
            self.cache=None
            if not keys: self.raster_cache.clear()
        elif self.cache is None or self.cache[0]!=signature:
            self.raster_cache.retain(keys)
            origin,image=render_layer(keys,frame,width,height,before,after,self.ghost.value()/100,cache=self.raster_cache,region=True)
            if v.flip_h or v.flip_v:
                origin=(width-origin[0]-image.width() if v.flip_h else origin[0],height-origin[1]-image.height() if v.flip_v else origin[1])
                image=image.mirrored(v.flip_h,v.flip_v)
            self.cache=(signature,image,origin)
        if not accelerated and self.cache is not None:
            _,image,origin=self.cache
            target=QRectF(rect.x()+origin[0]*rect.width()/width,rect.y()+origin[1]*rect.height()/height,image.width()*rect.width()/width,image.height()*rect.height()/height)
            painter.drawImage(target,image)
        if adornments and not (getattr(self.win,'clip_tools',None) and self.win.clip_tools.mode): self.selection.paint(painter,rect)
        if self.size_drag and self.size_point:
            reference=next(iter(self.win.doc.media.values()),{}); radius=self.size.value()/max(1,reference.get('height',720))*rect.height()/2
            center=self.selection.display_transform(rect).map(QPointF(*self.size_point)); painter.save(); pen=QPen(QColor('#ffffff'),1); pen.setCosmetic(True); painter.setPen(pen); painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawEllipse(center,radius,radius); painter.restore()
        if self.text_drag:
            path=QPainterPath(); path.addRect(self.pending_text_rect()); self.selection.paint_outline(painter,rect,path)

