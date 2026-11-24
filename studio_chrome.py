# SPDX-License-Identifier: GPL-3.0-only
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt
from shiboken6 import isValid
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QFrame, QHBoxLayout, QLabel, QLayout,
                               QMenu, QScrollArea, QSizePolicy, QToolBar,
                               QToolButton, QVBoxLayout, QWidget)

from studio_icons import icon
from ui_text import language, tr


class FileLabel(QLabel):
    def __init__(self, name):
        super().__init__()
        self.setObjectName(name)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.value = ''

    def set_value(self, value):
        if value != self.value:
            self.value = value
            self.setToolTip(value)
            self.fit_text()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_text()

    def fit_text(self):
        self.setText(self.fontMetrics().elidedText(self.value, Qt.TextElideMode.ElideMiddle,
                                                   self.contentsRect().width()))


def frame_clock(frame, fps):
    second, subframe = divmod(frame, max(1, round(fps)))
    hour, rest = divmod(second, 3600)
    minute, second = divmod(rest, 60)
    return f'{hour:02}:{minute:02}:{second:02}:{subframe:02}'


def strip(name, height, padding=8):
    body = QFrame()
    body.setObjectName(name)
    body.setFixedHeight(height)
    row = QHBoxLayout(body)
    row.setContentsMargins(padding, 0, padding, 0)
    row.setSpacing(5)
    return body, row


def glyph(symbol, size=16, color=None):
    label = QLabel()
    label.setObjectName('studioGlyph')
    label.setPixmap(icon(symbol, color, size).pixmap(size, size))
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


def divider():
    line = QFrame()
    line.setObjectName('studioDivider')
    line.setFixedSize(1, 18)
    return line


def control(name, symbol=None, caption=None, action=None, size=17):
    b = QToolButton()
    if action:
        if symbol:
            action.setIcon(icon(symbol))
        if caption:
            action.setIconText(tr(caption))
        b.setDefaultAction(action)
    b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon if caption else Qt.ToolButtonStyle.ToolButtonIconOnly)
    b.setIconSize(QSize(size, size))
    if not caption:
        b.setFixedWidth(30)
    b.setFixedHeight(30)
    def update():
        b.setToolTip((action.toolTip() or tr(name)) if action else tr(name))
        b.setAccessibleName(tr(name))
        if symbol:
            b.setIcon(icon(symbol, size=size))
        if caption:
            b.setText(tr(caption))
    if action:
        action.changed.connect(update)
    update()
    return b


def build_editing_strip(w):
    from widgets import ScrubDoubleSpinBox
    body, row = strip('studioEditing', 44, 12)
    row.setSpacing(8)
    contents = QWidget()
    controls = QHBoxLayout(contents)
    controls.setContentsMargins(0, 0, 2, 0)
    controls.setSpacing(8)
    controls.addWidget(glyph('settings'))
    controls.addWidget(QLabel(tr('Exposition')))
    w.exp_spin = ScrubDoubleSpinBox()
    w.exp_spin.setRange(-10, 10)
    w.exp_spin.setDecimals(2)
    w.exp_spin.setSingleStep(.25)
    w.exp_spin.setSuffix(tr(' EV'))
    w.exp_spin.setAccessibleName(tr('Exposition'))
    w.exp_spin.setFixedSize(max(78,w.exp_spin.minimumSizeHint().width()), 27)
    w.exp_spin.valueChanged.connect(w.exposure_spin)
    w.exp_spin.editingFinished.connect(w.commit_exposure)
    controls.addWidget(w.exp_spin)
    reset = control('Réinitialiser l’exposition', 'refresh', size=15)
    reset.clicked.connect(lambda:w.set_exposure(0))
    controls.addWidget(reset)
    w.apply_export = QCheckBox(tr('Appliquer à l’export'))
    w.apply_export.setChecked(True)
    controls.addWidget(w.apply_export)
    controls.addWidget(divider())
    w.editing_flags = QWidget()
    flags = QHBoxLayout(w.editing_flags)
    flags.setContentsMargins(0, 0, 0, 0)
    flags.setSpacing(10)
    flags.addWidget(glyph('edit'))
    flags.addWidget(QLabel(tr('Montage')))
    w.editing_overflow = control('Montage', 'edit', 'Montage')
    choices = QMenu(w.editing_overflow)
    w.editing_overflow.setMenu(choices)
    w.editing_overflow.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    def menu_toggle(box):
        a = choices.addAction(box.text())
        a.setCheckable(True)
        a.setChecked(box.isChecked())
        a.toggled.connect(box.setChecked)
        box.toggled.connect(a.setChecked)
    menu_toggle(w.apply_export)
    choices.addSeparator()
    for attr, name, checked, hint in (
        ('copy_audio', 'Copier/coller le son', False, 'Décoché : les images collées sont accompagnées de silence. Cocher avant de copier pour inclure le son.'),
        ('leave_gap', 'Laisser un vide', False, 'Alt-déplacement : conserver un vide à la place du bloc déplacé.'),
        ('link_tracks', 'Audio / vidéo liés', True, 'Désactiver pour déplacer uniquement la piste saisie avec Alt.'),
        ('link_drawings', 'Dessins / vidéo liés', True, 'Les clés suivent les déplacements, coupes et insertions vidéo. Décocher pour garder le calque indépendant.'),
    ):
        box = QCheckBox(tr(name))
        box.setToolTip(tr(hint))
        box.setChecked(checked)
        setattr(w, attr, box)
        flags.addWidget(box)
        menu_toggle(box)
    w.link_drawings.toggled.connect(w.set_drawings_linked)
    controls.addWidget(w.editing_flags)
    controls.addWidget(w.editing_overflow)
    controls.addStretch()
    w.header_scroll = QScrollArea()
    w.header_scroll.setFrameShape(QFrame.Shape.NoFrame)
    w.header_scroll.setWidgetResizable(True)
    w.header_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    w.header_scroll.setWidget(contents)
    row.addWidget(w.header_scroll, 1)
    row.addWidget(divider())
    for attr, title, symbol, shortcut, callback in (
        ('open_btn', 'Ouvrir des vidéos', 'folder', 'Ctrl+O', w.open_video),
        ('save_btn', 'Enregistrer', 'doc', 'Ctrl+S', w.save_project),
        ('export_btn', 'Exporter', 'export', 'Ctrl+E', w.export_dialog),
    ):
        b = control(title, symbol, title)
        b.setProperty('fileCommand', True)
        b.setToolTip(tr(title) + ' · ' + shortcut)
        b.clicked.connect(callback)
        row.addWidget(b)
        setattr(w, attr, b)
    return body


class StudioChrome(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.w = window
        self.drawing_panel_width = window.drawing.panel.minimumWidth()
        window.drawing.panel.layout().setSizeConstraint(QLayout.SetNoConstraint)
        self.build_top()
        self.build_viewer()
        self.build_rail()
        self.build_timeline()
        self.build_transport()
        from studio_hover import HoverHeaders
        self.headers = HoverHeaders(self)
        self.w.library_tabs.setCurrentIndex(max(0, min(self.w.library_tabs.count()-1,
            self.w.settings.value('library/last_tab', 2, type=int))))
        self.w.library_tabs.currentChanged.connect(lambda index:self.w.settings.setValue('library/last_tab', index))
        self.w.installEventFilter(self)
        self.responsive()

    def build_top(self):
        w = self.w
        self.bar = QToolBar(tr('Cadence'), w)
        self.bar.setObjectName('studioTopBar')
        self.bar.setMovable(False)
        self.bar.setFloatable(False)
        self.bar.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        frame, row = strip('studioTop', 53, 16)
        self.top = frame
        row.setSpacing(8)
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        logo = QLabel()
        logo.setPixmap(w.windowIcon().pixmap(24, 24))
        row.addWidget(logo)
        self.brand = QLabel('Cadence')
        self.brand.setObjectName('studioBrand')
        row.addWidget(self.brand)
        row.addSpacing(5)
        self.menu_button = control('Menu', 'menu', 'Menu')
        self.menu_button.setObjectName('studioMenuButton')
        self.menu = QMenu(self.menu_button)
        for entry in w.menuBar().actions():
            self.menu.addAction(entry)
        self.menu_button.setMenu(self.menu)
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        row.addWidget(self.menu_button)
        row.addWidget(divider())
        self.project_icon = glyph('doc', 15, '#9aaabb')
        row.addWidget(self.project_icon)
        self.project = FileLabel('studioProject')
        row.addWidget(self.project)
        self.breadcrumb = FileLabel('studioDetails')
        row.addWidget(self.breadcrumb)
        for field in (self.project, self.breadcrumb):
            field.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        row.addStretch(1)
        group, buttons = strip('studioModes', 36, 3)
        buttons.setSpacing(3)
        self.mode_buttons = {}
        for mode, name, symbol in [('read','Lecture','play'),('edit','Édition','edit')]:
            b = control(name, symbol, name, size=13 if mode == 'read' else 15)
            b.setFixedHeight(28)
            b.setCheckable(True)
            b.setObjectName('studioMode')
            b.clicked.connect(lambda checked=False,m=mode:self.choose_mode(m))
            buttons.addWidget(b)
            self.mode_buttons[mode] = b
        group.setParent(frame)
        self.mode_group = group
        row.addSpacing(4)
        row.addWidget(control('Options…', 'settings', action=w.action_registry['Fichier/Options…'][0]))
        row.addWidget(control('Guide rapide', 'help', action=w.action_registry['Aide/Guide rapide'][0]))
        row.addWidget(divider())
        self.language_button = control('Langue', caption='FR / en' if language() == 'fr' else 'EN / fr')
        self.language_button.clicked.connect(w.toggle_language)
        row.addWidget(self.language_button)
        self.top_slot=QWidget()
        self.top_slot.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        top_layout=QVBoxLayout(self.top_slot)
        top_layout.setContentsMargins(0,0,0,0)
        top_layout.addWidget(frame)
        self.bar.addWidget(self.top_slot)
        w.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.bar)
        w.menuBar().hide()
        self.menu_key = QShortcut(QKeySequence('F10'), w)
        self.menu_key.activated.connect(self.open_menu)

    def open_menu(self):
        if self.w.video_fullscreen: self.w.toggle_fullscreen()
        if self.headers.read: self.headers.show_reader()
        if entrance := getattr(self.top,'entrance',None):
            entrance.finish()
        self.menu.popup(self.menu_button.mapToGlobal(self.menu_button.rect().bottomLeft()))

    def center_modes(self):
        width=self.top.width()
        size=self.mode_group.sizeHint()
        left=(width-size.width())//2
        if getattr(getattr(self, 'headers', None), 'read', False):
            center=self.top.mapFromGlobal(self.w.mapToGlobal(self.w.rect().center())).x()
            gap=8 if self.project.isHidden() else 20
            left=max(self.menu_button.geometry().right()+gap, min(center-size.width()//2, width-155-size.width()))
        self.mode_group.setGeometry(left,(self.top.height()-size.height())//2,size.width(),size.height())
        if self.project.isHidden(): return
        available=max(0,left-270)
        wanted=self.project.fontMetrics().horizontalAdvance(self.project.value)+2
        self.project.setFixedWidth(min(220,available,wanted))
        self.breadcrumb.setFixedWidth(min(135,max(0,available-self.project.width()-8),self.breadcrumb.fontMetrics().horizontalAdvance(self.breadcrumb.value)+1))

    def choose_mode(self, mode):
        if mode != self.w.workspaces.mode:
            self.w.workspaces.switch(mode)
        else:
            self.sync_mode(mode, self.w.timeline.simple)

    def sync_menu_shortcut(self):
        used = any(shortcut == QKeySequence('F10') for a,_ in self.w.action_registry.values() for shortcut in a.shortcuts())
        self.menu_key.setEnabled(not used)

    def build_viewer(self):
        w = self.w
        self.view, row = strip('studioView', 42, 10)
        self.viewer_row = row
        row.setSpacing(7)
        self.side_history={}
        self.dock_button = control('Panneau gauche', 'dock')
        self.dock_button.clicked.connect(lambda:self.toggle_side('left'))
        row.addWidget(self.dock_button)
        self.view_divider = divider()
        row.addWidget(self.view_divider)
        self.media = FileLabel('studioSource')
        row.addWidget(self.media, 1)
        self.format = QLabel()
        self.format.setObjectName('studioDetails')
        row.addWidget(self.format)
        self.format_divider=divider()
        row.addWidget(self.format_divider)
        self.compare_button = control('Activer la comparaison', 'ab', 'A/B', w.compare_action)
        row.addWidget(self.compare_button)
        sync_settings = w.action_registry['Synchronisation 3D/Réglages de synchronisation…'][0]
        self.sync_button = control('Réglages de synchronisation…', 'sync-3d', action=sync_settings)
        row.addWidget(self.sync_button)
        self.right_button = control('Panneau droit','dock-right')
        self.right_button.clicked.connect(lambda:self.toggle_side('right'))
        row.addWidget(self.right_button)
        menu = QMenu(self.view)
        for key in ('header','drawing','comparison','timecode','transport','timeline','tools'):
            menu.addAction(w.panel_actions[key])
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(lambda point:menu.exec(self.view.mapToGlobal(point)))
        row.addWidget(control('Plein écran vidéo', 'fit', action=w.action_registry['Affichage/Plein écran vidéo'][0]))
        central = w.viewer_workspace.content.layout()
        central.setContentsMargins(0, 0, 0, 0)
        central.setSpacing(0)
        central.removeWidget(w.viewer)
        self.stage = QFrame()
        self.stage.setObjectName('studioStage')
        self.stage_layout = QVBoxLayout(self.stage)
        self.stage_layout.setContentsMargins(17, 9, 17, 9)
        self.stage_layout.addWidget(w.viewer)
        central.addWidget(self.stage, 1)
        central.insertWidget(0, self.view)

    def side_docks(self, side):
        area=Qt.LeftDockWidgetArea if side=='left' else Qt.RightDockWidgetArea
        w=self.w
        return {name:dock for name,dock in (('library',w.library),('comparison',w.comparison_panel),('drawing',w.drawing.panel))
                if not dock.isFloating() and w.dockWidgetArea(dock)==area}

    def toggle_side(self,side):
        docks=self.side_docks(side)
        shown=[name for name,dock in docks.items() if not dock.isHidden()]
        key=self.w.workspaces.mode+'/'+side
        if shown:
            self.side_history[key]=shown
            for name in shown: docks[name].hide()
        else:
            wanted=[name for name in self.side_history.get(key,()) if name in docks]
            for name in wanted or list(docks)[:1]:
                dock=docks[name]
                dock.show()
                if self.w.workspaces.mode=='read':
                    from studio_hover import slide_in
                    slide_in(dock.widget(),QPoint(-20 if side=='left' else 20,0))
        self.align_workspace()

    def build_rail(self):
        w = self.w
        scroll = w.edit_toolbar.widget()
        rail = QFrame()
        rail.setObjectName('studioRail')
        stack = QVBoxLayout(rail)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(0)
        tools = QFrame()
        tools.setObjectName('studioRailTools')
        items = QVBoxLayout(tools)
        self.rail_items = items
        items.setContentsMargins(0, 9, 0, 5)
        items.setSpacing(3)
        items.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        def add(button):
            button.setFixedSize(29, 29)
            items.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)
            return button
        actions = list(w.drawing.tool_actions.items())
        actions += [(tool,w.action_registry['Outils/'+name][0]) for tool,name in
                    (('resize','Transformer la sélection ou le clip'),('crop','Recadrer le clip'))]
        self.rail_buttons={}
        for key, action in actions:
            b = add(control(action.text(), {'brush':'pen','eraser':'erase'}.get(key,key), action=action))
            b.setProperty('railTool', True)
            self.rail_buttons[key]=b
        items.addSpacing(1)
        rule = QFrame()
        rule.setObjectName('studioRailRule')
        rule.setFixedSize(17, 1)
        items.addWidget(rule, 0, Qt.AlignmentFlag.AlignHCenter)
        items.addSpacing(1)
        swatch = add(control('Couleur du crayon'))
        layout = QHBoxLayout(swatch)
        layout.setContentsMargins(0, 0, 0, 0)
        dot = QFrame()
        dot.setFixedSize(15, 15)
        dot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(dot, 0, Qt.AlignmentFlag.AlignCenter)
        def update_color(value):
            dot.setStyleSheet(f'background:{value};border:2px solid #c8d4dc;border-radius:7px')
        def choose_color():
            color = QColorDialog.getColor(QColor(w.drawing.wheel.color()), w, tr('Couleur du crayon'))
            if color.isValid():
                w.drawing.hex.setText(color.name())
                w.drawing.read_color()
        w.drawing.wheel.changed.connect(update_color)
        w.drawing.wheel.set_color('#ffd096')
        swatch.clicked.connect(choose_color)
        add(control('Annuler', 'undo', action=w.undo_action))
        tools_menu = w.drawing.tools_menu
        tools.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tools.customContextMenuRequested.connect(lambda point:tools_menu.exec(tools.mapToGlobal(point)))
        for button in self.rail_buttons.values():
            button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            button.customContextMenuRequested.connect(lambda point,b=button:tools_menu.exec(b.mapToGlobal(point)))
        scroll.setWidget(tools)
        scroll.setMinimumWidth(0)
        scroll.setStyleSheet('QScrollArea{border:0;background:#151c23;} QScrollBar:vertical {width:3px;background:#151c23;} QScrollBar::handle:vertical{background:#465562;min-height:12px;} QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}')
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setParent(rail)
        stack.addWidget(scroll, 1)
        w.edit_toolbar.setWidget(rail)
        for obj in (w.edit_toolbar, w.library, w.comparison_panel, w.drawing.panel, w.viewer_workspace, self.top):
            obj.installEventFilter(self)

    def build_timeline(self):
        w = self.w
        panel = w.timeline_panel.widget().layout()
        panel.setSpacing(0)
        self.collapsed = False
        self.timeline_bar, row = strip('studioTimeline', 39, 12)
        row.setSpacing(8)
        self.fold = control('Replier ou déplier la timeline', 'down', size=13)
        self.fold.setFixedSize(17, 23)
        self.fold.clicked.connect(self.fold_timeline)
        row.addWidget(self.fold)
        row.addWidget(glyph('edit', 17))
        name = QLabel(tr('Timeline'))
        name.setObjectName('studioSection')
        row.addWidget(name)
        self.track_count = QLabel()
        self.track_count.setObjectName('studioDetails')
        row.addSpacing(7)
        row.addWidget(self.track_count)
        row.addStretch()
        self.views = []
        chooser, choices = strip('studioSegment', 26, 2)
        choices.setSpacing(1)
        for simple, name, symbol in [(True,'Simplifiée','minus'),(False,'Détaillée','edit')]:
            b = control(name, symbol, name, size=13)
            b.setFixedHeight(22)
            b.setCheckable(True)
            b.clicked.connect(lambda checked=False,v=simple:w.workspaces.set_timeline_simple(v))
            choices.addWidget(b)
            self.views.append(b)
        row.addWidget(chooser)
        units, choices = strip('studioSegment', 26, 2)
        choices.setSpacing(0)
        self.units = []
        for key,name,caption in [('time','Timecode','s'),('frames','Frames','im.')]:
            b = control(name, caption=caption)
            b.setFixedHeight(22)
            b.setCheckable(True)
            b.clicked.connect(lambda checked=False,v=key:w.timeline.set_units(v))
            choices.addWidget(b)
            self.units.append(b)
        row.addWidget(units)
        w.timeline.unitsChanged.connect(self.sync_units)
        self.sync_units(w.timeline.units)
        panel.insertWidget(0, self.timeline_bar)
        w.timeline.install_scrub_band(self.timeline_bar)
        w.sync_timeline_scroll()

    def fold_timeline(self):
        self.collapsed = not self.collapsed
        self.fold.setIcon(icon('right' if self.collapsed else 'down', size=13))
        self.w.timeline.setVisible(not self.collapsed)
        self.headers.configure(self.headers.read, self.w.timeline.simple and not self.collapsed)
        self.w.sync_timeline_scroll()

    def build_transport(self):
        w = self.w
        w.media_info.hide()
        w.transport_left.setContentsMargins(0, 0, 0, 0)
        w.transport_left.setSpacing(10)
        w.transport_center.setContentsMargins(0, 0, 0, 0)
        w.transport_center.setSpacing(2)
        w.transport_center.insertWidget(w.transport_center.indexOf(w.loop_btn), divider())
        w.compare_controls.setVisible(w.compare_enabled.isChecked())
        w.compare_enabled.toggled.connect(w.compare_controls.setVisible)
        for i in range(w.transport_center.count()):
            b = w.transport_center.itemAt(i).widget()
            if b:
                b.setProperty('studioTransport', True)
        w.transport_widget.widget().setObjectName('studioTransport')

    def sync_mode(self, mode, simple):
        for key,b in self.mode_buttons.items():
            b.setChecked(key == mode)
            b.setIcon(icon('edit' if key=='edit' else 'play', color='#112b29' if key==mode else '#d3deea'))
        self.views[0].setChecked(simple)
        self.views[1].setChecked(not simple)
        self.timeline_bar.setFixedHeight(30 if self.w.height() <= 440 else 34 if mode == 'read' else 39)
        self.headers.configure(mode=='read',simple and not self.collapsed)
        self.w.sync_timeline_scroll()

    def sync_units(self, units):
        for b,key in zip(self.units, ('time','frames')):
            b.setChecked(key == units)

    def update_document(self, title):
        project = Path(self.w.doc.project_path) if self.w.doc.project_path else None
        name = ('● ' if self.w.doc.dirty else '') + (project.name if project else title)
        self.project.setFixedWidth(min(220, self.project.fontMetrics().horizontalAdvance(name) + 2))
        self.project.set_value(name)
        folder = '/ ' + project.parent.name if project and project.parent.name else ''
        self.breadcrumb.setFixedWidth(min(135, self.breadcrumb.fontMetrics().horizontalAdvance(folder) + 1))
        self.breadcrumb.set_value(folder)
        self.breadcrumb.setVisible(bool(folder) and self.w.width() > 1000)
        self.center_modes()
        self.track_count.setText(tr('2 pistes média') if self.w.doc.state.second_track else tr('1 piste média'))

    def update_media(self, media, info):
        self.media.set_value(media['name'] if media else tr('Aperçu'))
        if media and media.get('has_video', True):
            rate = f'{float(self.w.doc.fps):.3f}'.rstrip('0').rstrip('.')
            info = f'{media["width"]} × {media["height"]} · {rate} {tr("i/s")}'
        self.format.setText('' if info == '-' else info)

    def eventFilter(self, obj, event):
        if isValid(self.w) and hasattr(self,'headers') and event.type() in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show, QEvent.Type.Hide):
            if obj is self.w:
                self.responsive()
            elif obj is self.top:
                self.center_modes()
            else:
                self.align_workspace()
        return False

    def align_workspace(self):
        w = self.w
        for side,button,hide,show in (('left',self.dock_button,'Cacher le panneau gauche','Afficher le panneau gauche'),
                                      ('right',self.right_button,'Cacher le panneau droit','Afficher le panneau droit')):
            docks=self.side_docks(side)
            shown=any(not p.isHidden() for p in docks.values())
            text=tr(hide if shown else show)
            button.setEnabled(bool(docks))
            button.setToolTip(text)
            button.setAccessibleName(text)
            button.setCheckable(True)
            button.setChecked(shown)
        w.compact_transport.schedule()

    def fit_sidebar(self):
        dock = self.w.library
        if dock.isHidden() or dock.isFloating():
            return
        wanted = 208 if self.w.width() <= 760 else 226 if self.w.width() <= 1000 else 262
        self.w.resizeDocks([dock], [wanted], Qt.Orientation.Horizontal)

    def stage_padding(self,read):
        if read or self.w.video_fullscreen: return (0,0,0,0)
        x,y=(4,4) if self.w.width()<=760 else (17,9)
        if self.w.height()<=440: y=0
        return (x,y,x,y)

    def responsive(self):
        small = self.w.width() <= 1000
        narrow = self.w.width() <= 760
        low = self.w.height() <= 620
        short = self.w.height() <= 440
        self.w.drawing.panel.setMinimumWidth(200 if narrow else self.drawing_panel_width)
        self.format.setVisible(not small)
        self.format_divider.setVisible(not narrow)
        self.view_divider.setVisible(not narrow)
        self.viewer_row.setContentsMargins(2 if narrow else 10,0,2 if narrow else 10,0)
        self.viewer_row.setSpacing(2 if narrow else 7)
        self.compare_button.setToolButtonStyle(Qt.ToolButtonTextOnly if narrow else Qt.ToolButtonTextBesideIcon)
        self.project_icon.setVisible(not narrow)
        self.project.setVisible(not narrow)
        self.breadcrumb.setVisible(not small and bool(self.breadcrumb.value))
        self.track_count.setVisible(not narrow)
        self.top.setFixedHeight(36 if short else 42 if low else 53)
        edit_strip = self.w.header.widget()
        strip_height = 36 if short else 44
        if edit_strip.minimumHeight() != strip_height:
            edit_strip.setFixedHeight(strip_height)
            self.w.compact_playback_panels()
        self.view.setFixedHeight(34 if low else 42)
        self.rail_items.setContentsMargins(0, 3 if low else 9, 0, 3 if low else 5)
        self.rail_items.setSpacing(0 if low else 3)
        geometry_band = (small, narrow)
        if hasattr(self, 'last_band') and self.last_band != geometry_band:
            self.fit_sidebar()
        self.last_band = geometry_band
        if hasattr(self.w, 'workspaces'):
            read = self.w.workspaces.mode == 'read'
            self.timeline_bar.setFixedHeight(30 if short else 34 if read else 39)
        self.w.sync_timeline_scroll()
        self.stage_layout.setContentsMargins(*self.stage_padding(self.headers.read))
        self.center_modes()
        condensed = self.w.width() < 1480
        self.w.viewer.setMinimumHeight(70 if short else 90)
        self.w.editing_flags.setVisible(not condensed)
        self.w.editing_overflow.setVisible(condensed)
        self.w.apply_export.setVisible(not narrow)
        for button in (self.w.open_btn,self.w.save_btn,self.w.export_btn):
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly if narrow
                                      else Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.align_workspace()
