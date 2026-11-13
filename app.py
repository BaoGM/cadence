# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import time as _startup_time
_STARTUP=_startup_time.perf_counter()
import sys
if __name__=='__main__' and '--register-associations' in sys.argv:
    from association import register
    register()
    if '--no-settings' not in sys.argv:
        import os
        os.startfile('ms-settings:defaultapps')
    raise SystemExit(0)
if __name__=='__main__' and not any(arg.startswith('--self-test') for arg in sys.argv):
    from diagnostics import initialize
    initialize()
from ui_text import tr
from platform_support import WINDOWS
import logging, sys, json
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
import numpy as np
logging.info('Startup base imports: %.3fs',_startup_time.perf_counter()-_STARTUP)
from PySide6.QtCore import Qt, QTimer, QSignalBlocker, QUrl, QSettings
from PySide6.QtGui import QAction, QKeySequence, QDesktopServices, QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QCheckBox, QFileDialog, QMessageBox, QProgressDialog, QLineEdit, QAbstractSpinBox, QSplitter, QScrollArea, QInputDialog, QDockWidget, QListWidget, QListWidgetItem, QTabWidget, QMenu, QScrollBar, QAbstractItemView, QToolButton, QDialog, QTextBrowser, QDialogButtonBox, QToolBar
logging.info('Startup Qt imports cumulative: %.3fs',_startup_time.perf_counter()-_STARTUP)
from model import Document, locate
from media import prepare_batch, prepare_media, validate_media, export_video, cache_root, Cancelled, display_waveform
from engine import Task, Decoder, Transport
from widgets import Viewer, Timeline, ScrubDoubleSpinBox, VolumeBars, TransportButton
from preferences import load_preferences, ShortcutDialog
from comparison import ComparisonMixin
from draw_ui import DrawController
from PySide6.QtWidgets import QGridLayout

VERSION='1.16.1'
STYLE='''
QMainWindow, QWidget { background:#11161d; color:#dce4ee; font-family:"Segoe UI"; font-size:13px; }
QMenuBar { background:#11161d; color:#91a1b5; padding:3px; }
QMenuBar::item:selected,QMenu::item:selected { background:#2b3947; }
QMenu { background:#1b2430; border:1px solid #354354; padding:5px; }
QMenu::separator { height:1px; background:#354354; margin:6px 8px; }
QLabel#brand {font-size:23px;font-weight:700;color:#f1f6fb;}
QLabel#eyebrow {font-size:10px;font-weight:700;color:#73869c;letter-spacing:2px;}
QLabel#muted {color:#8192a6;font-size:12px;}
QLabel#section {font-size:14px;font-weight:600;color:#ebf2f8;}
QFrame#panel {background:#191f29;border:1px solid #2a3441;border-radius:9px;}
QFrame#panel QLabel,QFrame#panel QWidget {background:transparent;}
QPushButton {background:#222d3a;border:1px solid #344151;border-radius:6px;padding:8px 13px;color:#dfe8f3;}
QPushButton:hover {background:#2d3b4b;border-color:#60758b;}
QPushButton:pressed {background:#35475b;}
QPushButton:disabled {color:#536174;background:#1b222c;border-color:#28313d;}
QPushButton#primary {background:#68e0cf;color:#10221f;border:0;font-weight:700;}
QPushButton#primary:hover {background:#91ecdd;}
QPushButton#danger {color:#f1b3a6;}
QToolButton:checked {background:#355558;border:1px solid #68e0cf;border-radius:4px;}
QPushButton#transport {font-size:16px;min-width:28px;}
QComboBox,QSpinBox,QDoubleSpinBox,QLineEdit {background:#111720;border:1px solid #354254;border-radius:5px;padding:6px;color:#dfe8f1;min-height:20px;}
QComboBox::drop-down {border:0;width:18px;}
QComboBox QAbstractItemView {background:#243040;selection-background-color:#42616b;}
QSlider::groove:horizontal {height:4px;background:#344354;border-radius:2px;}
QSlider::sub-page:horizontal {background:#68e0cf;border-radius:2px;}
QSlider::handle:horizontal {background:#d5fff7;border:2px solid #68e0cf;width:12px;height:12px;margin:-5px 0;border-radius:7px;}
QCheckBox {spacing:7px;}
QCheckBox::indicator {width:15px;height:15px;border:1px solid #5b6c81;border-radius:3px;background:#141a22;}
QCheckBox::indicator:checked {background:#68e0cf;border-color:#68e0cf;}
QCheckBox:disabled {color:#687586;}
QCheckBox::indicator:disabled {background:#1b222c;border-color:#344151;}
QCheckBox::indicator:checked:disabled {background:#41615e;border-color:#41615e;}
QStatusBar {background:#0e1319;color:#7f91a7;}
QToolTip {background:#253243;color:#edf5ff;border:1px solid #536579;padding:5px;}
QSplitter::handle {background:#11161d;height:9px;}
QScrollBar:horizontal {background:#151d27;height:14px;border:0;}
QScrollBar::handle:horizontal {background:#52687a;min-width:28px;border-radius:5px;}
QScrollBar::handle:horizontal:hover {background:#68e0cf;}
QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal {width:0;}
QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal {background:#151d27;}
QProgressBar {border:1px solid #354254;border-radius:4px;text-align:center;background:#141a23;}
QProgressBar::chunk {background:#68e0cf;}
'''

def label(text,name=None):
    obj=QLabel(tr(text))
    if name: obj.setObjectName(name)
    return obj

def button(text,fn,name=None,tip=None):
    b=QPushButton(tr(text)); b.setMinimumHeight(34); b.clicked.connect(fn)
    if name: b.setObjectName(name)
    if tip: b.setToolTip(tr(tip))
    return b

class MainWindow(ComparisonMixin,QMainWindow):
    def __init__(self):
        from diagnostics import StartupTimer
        startup=StartupTimer()
        super().__init__(); self.doc=Document(); self.token=0; self.job=None; self.dialog=None
        from ui_text import initialize_language
        initialize_language()
        from ui_style import install_tooltip_delay
        install_tooltip_delay()
        from file_dialogs import install_file_places
        install_file_places()
        from dialogs import install_dialog_presentation
        install_dialog_presentation()
        startup.checkpoint('language and styles')
        self.display_frame=-1; self.selection_anchor=None; self.last_pass=1; self.playback_mode='once'; self.exp_pending=0; self.rendered_token=-1; self.play_completed=False
        self.setAcceptDrops(True)
        import os
        isolated=os.environ.get('CADENCE_PREFS')
        if isolated:
            from PySide6.QtCore import QSettings as SettingsType
            self.settings=QSettings(str(Path(isolated).with_name('settings.ini')),SettingsType.Format.IniFormat)
        else: self.settings=QSettings('CadenceStudio','CadenceStudio')
        self.video_fullscreen=False
        self.setWindowIcon(QIcon(str(Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'assets'/'cadence.ico')))
        self.setWindowTitle(tr('Cadence')); self.resize(1360,890); self.setMinimumSize(640,400)
        from cache_ram import FrameCache
        self.frame_cache=FrameCache()
        self.transport=Transport(self); self.decoder=Decoder(self); self.decoder.ready.connect(self.frame_ready); self.decoder.failed.connect(self.frame_failed); self.decoder.start()
        from scrub_audio import ScrubAudio
        self.scrub_audio=ScrubAudio(self)
        from audio_jobs import AudioJobs
        self.audio_jobs=AudioJobs(self); self.audio_jobs.ready.connect(self.prepared_audio)
        self.audio_jobs.status.connect(self.audio_preparation_status)
        self.audio_jobs.failed.connect(lambda message:self.error(tr('Préparation audio impossible.')+'\n'+message))
        self.timer=QTimer(self); self.timer.setInterval(10); self.timer.setTimerType(Qt.TimerType.PreciseTimer); self.timer.timeout.connect(self.tick)
        self.exp_timer=QTimer(self); self.exp_timer.setSingleShot(True); self.exp_timer.setInterval(300); self.exp_timer.timeout.connect(self.commit_exposure)
        startup.checkpoint('audio and decoder initialization')
        self.clipboard_kind='media'; self.action_registry={}; self.build_ui(); startup.checkpoint('panels')
        self.build_menus(); self.preferences=load_preferences(self.action_registry); self.apply_preferences(self.preferences); self.set_layout_editable(False)
        startup.checkpoint('menus and preferences')
        from capture import StopHotkey
        self.capture_dialog=None; self.capture_hotkey=StopHotkey(lambda:self.capture_screen(True))
        self.capture_hotkey.register()
        self.resizeDocks([self.library,self.comparison_panel,self.drawing.panel,self.edit_toolbar],[280,280,285,48],Qt.Orientation.Horizontal)
        from workspace_modes import WorkspaceModes
        self.initial_dock_state=self.saveState()
        self.workspaces=WorkspaceModes(self)
        from menu_layout import BackgroundPanelMenu
        self.background_panel_menu=BackgroundPanelMenu(self)
        from wipe import WipeInteraction
        self.wipe_interaction=WipeInteraction(self.viewer)
        self.viewer.installEventFilter(self.timecode_overlay)
        self.refresh()
        self.viewer.setFocus(Qt.FocusReason.OtherFocusReason)
        from session import SessionRecovery
        self.session=SessionRecovery(self)
        startup.checkpoint('workspace and session')
        from playback_preferences import load,save
        load(self)
        self.playback_prefs_timer=QTimer(self); self.playback_prefs_timer.setSingleShot(True); self.playback_prefs_timer.setInterval(300)
        self.playback_prefs_timer.timeout.connect(lambda:save(self))
        for signal in (self.volume.valueChanged,self.volume.mutedChanged,self.timeline.unitsChanged,self.timecode_overlay.positionChanged,self.timecode_overlay.lockChanged): signal.connect(lambda *args:self.playback_prefs_timer.start())

    def build_ui(self):
        central=QWidget(); self.setCentralWidget(central); layout=QVBoxLayout(central); layout.setContentsMargins(22,12,22,8); layout.setSpacing(14)
        self.header=QWidget(); top=QHBoxLayout(self.header); top.setContentsMargins(12,2,12,2); top.setSpacing(12)
        self.header.setStyleSheet('QWidget {font-size:12px;} QLabel#section {font-size:12px;} QPushButton {padding:6px 8px;} QCheckBox {spacing:4px;} QCheckBox::indicator {width:12px;height:12px;}')
        settings=QWidget(); settings_row=QHBoxLayout(settings); settings_row.setContentsMargins(0,0,0,0); settings_row.setSpacing(16)
        exposure=QHBoxLayout(); exposure.setSpacing(8); exposure.addWidget(label('Exposition','section'))
        self.exp_spin=ScrubDoubleSpinBox(); self.exp_spin.setRange(-10,10); self.exp_spin.setDecimals(2); self.exp_spin.setSingleStep(.25); self.exp_spin.setSuffix(tr(' EV')); self.exp_spin.setFixedWidth(max(100,self.exp_spin.minimumSizeHint().width()))
        self.exp_spin.valueChanged.connect(self.exposure_spin); self.exp_spin.editingFinished.connect(self.commit_exposure)
        exposure.addWidget(self.exp_spin); exposure.addWidget(button('Réinitialiser',lambda:self.set_exposure(0)))
        self.apply_export=QCheckBox(tr('Appliquer à l’export')); self.apply_export.setChecked(True); exposure.addWidget(self.apply_export); exposure.addStretch()
        settings_row.addLayout(exposure)
        files=QHBoxLayout(); files.setSpacing(8)
        self.open_btn=button('Ouvrir des vidéos',self.open_video,tip='Ctrl+O'); files.addWidget(self.open_btn)
        files.addWidget(button('Enregistrer',self.save_project,tip='Ctrl+S'))
        self.export_btn=button('Exporter  ↗',self.export_dialog,'primary'); files.addWidget(self.export_btn)
        montage=QHBoxLayout(); montage.setSpacing(8)
        montage_title=label('Montage','section'); montage_title.setStyleSheet('font-weight:600;color:#91a1b5;'); montage.addWidget(montage_title); montage.addSpacing(12)
        self.copy_audio=QCheckBox(tr('Copier/coller le son')); self.copy_audio.setChecked(False); self.copy_audio.setToolTip(tr('Décoché : les images collées sont accompagnées de silence. Cocher avant de copier pour inclure le son.')); montage.addWidget(self.copy_audio)
        self.leave_gap=QCheckBox(tr('Laisser un vide')); self.leave_gap.setToolTip(tr('Alt-déplacement : conserver un vide à la place du bloc déplacé.')); montage.addWidget(self.leave_gap)
        self.link_tracks=QCheckBox(tr('Audio / vidéo liés')); self.link_tracks.setChecked(True); self.link_tracks.setToolTip(tr('Désactiver pour déplacer uniquement la piste saisie avec Alt.')); montage.addWidget(self.link_tracks)
        self.link_drawings=QCheckBox(tr('Dessins / vidéo liés')); self.link_drawings.setChecked(True); self.link_drawings.setToolTip(tr('Les clés suivent les déplacements, coupes et insertions vidéo. Décocher pour garder le calque indépendant.')); self.link_drawings.toggled.connect(self.set_drawings_linked); montage.addWidget(self.link_drawings)
        settings_row.addStretch(1); settings_row.addLayout(montage); settings_row.addStretch(1)
        self.header_scroll=QScrollArea(); self.header_scroll.setFrameShape(QFrame.Shape.NoFrame); self.header_scroll.setWidgetResizable(True)
        self.header_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); self.header_scroll.setWidget(settings); self.header_scroll.setFixedHeight(48)
        self.header_scroll.setStyleSheet('QScrollBar:horizontal {height:6px;}'); top.addWidget(self.header_scroll,1); top.addLayout(files); layout.addWidget(self.header)
        split=QSplitter(Qt.Orientation.Vertical); layout.addWidget(split,1)
        upper=QWidget(); upper_layout=QHBoxLayout(upper); upper_layout.setContentsMargins(0,0,0,0); upper_layout.setSpacing(16)
        viewer_col=QVBoxLayout(); self.viewer_col=viewer_col; viewer_col.setSpacing(8)
        self.viewer=Viewer(); self.viewer.scrub.connect(lambda frame:self.seek(frame,audition=True)); self.viewer.scrubStarted.connect(self.begin_scrub); self.viewer.fileDropped.connect(self.drop_paths); self.viewer.fullscreenRequested.connect(self.toggle_fullscreen); self.viewer.openRequested.connect(self.open_video)
        viewer_col.addWidget(self.viewer,1)
        transport=QHBoxLayout(); transport.setContentsMargins(0,0,0,4); transport.setSpacing(3); self.transport_center=transport
        self.previous_key_btn=TransportButton('first',lambda:self.step_key(-1),'transport','Clé précédente · ,'); transport.addWidget(self.previous_key_btn)
        self.previous_frame_btn=TransportButton('previous',lambda:self.step(-1),'transport','Image précédente · ←'); transport.addWidget(self.previous_frame_btn)
        self.play_btn=TransportButton('play',self.toggle_play,'primary','Lecture / pause · Espace'); transport.addWidget(self.play_btn)
        self.next_frame_btn=TransportButton('next',lambda:self.step(1),'transport','Image suivante · →'); transport.addWidget(self.next_frame_btn)
        self.next_key_btn=TransportButton('last',lambda:self.step_key(1),'transport','Clé suivante · .'); transport.addWidget(self.next_key_btn)
        self.loop_btn=TransportButton('once',self.set_loop,tip='Lecture unique / boucle'); self.loop_btn.setCheckable(True); transport.addWidget(self.loop_btn)
        from timecode_overlay import TimecodeOverlay
        self.timecode_overlay=TimecodeOverlay(self.viewer); self.viewer.timecode_overlay=self.timecode_overlay
        self.volume=VolumeBars(); self.volume.valueChanged.connect(self.master_volume); self.volume.mutedChanged.connect(self.master_volume)
        self.transport_widget=QWidget(); row=QGridLayout(self.transport_widget); row.setContentsMargins(12,0,12,0); row.setHorizontalSpacing(12); row.setVerticalSpacing(0)
        left=QWidget(); left_row=QHBoxLayout(left); left_row.setContentsMargins(0,0,0,0); left_row.setSpacing(24); left_row.setAlignment(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter)
        mode_box=QWidget(); self.transport_left=QHBoxLayout(mode_box); self.transport_left.setContentsMargins(0,0,0,11); self.transport_left.setAlignment(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter)
        left_row.addWidget(mode_box,0,Qt.AlignmentFlag.AlignVCenter)
        center=QWidget(); center.setLayout(transport); self.transport_buttons=center
        right=QWidget(); info=QHBoxLayout(right); info.setContentsMargins(0,0,0,0); info.setSpacing(16); info.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.media_info=label('-','muted'); self.media_info.setContentsMargins(0,0,0,11); left_row.addWidget(self.media_info,0,Qt.AlignmentFlag.AlignVCenter); info.addWidget(self.volume,0,Qt.AlignmentFlag.AlignVCenter)
        self.audio_progress=label('','muted'); self.audio_progress.setContentsMargins(0,0,0,11); self.audio_progress.hide()
        left_row.addWidget(self.audio_progress,0,Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(left,0,0,Qt.AlignmentFlag.AlignVCenter); row.addWidget(center,0,1,Qt.AlignmentFlag.AlignVCenter); row.addWidget(right,0,2,Qt.AlignmentFlag.AlignVCenter)
        row.setColumnStretch(0,1); row.setColumnStretch(2,1); row.setColumnMinimumWidth(0,140); row.setColumnMinimumWidth(2,140)
        self.transport_widget.setFixedHeight(42); viewer_col.addWidget(self.transport_widget)
        from compact_transport import CompactTransport
        self.compact_transport=CompactTransport(self.transport_widget,left,center,right,self)
        upper_layout.addLayout(viewer_col,1)
        split.addWidget(upper)
        lower=QWidget(); lower_layout=QVBoxLayout(lower); lower_layout.setContentsMargins(0,0,0,0); lower_layout.setSpacing(8)
        self.timeline=Timeline(); self.timeline.seek.connect(self.timeline_seek); self.timeline.selected.connect(self.select); self.timeline.moved.connect(self.move_section); self.timeline.duplicated.connect(self.duplicate_section); self.timeline.deleteRequested.connect(self.delete_track_range); self.timeline.muteRequested.connect(self.mute_range); self.timeline.splitRequested.connect(self.split_cursor); self.timeline.deleteMediaRequested.connect(self.delete_media_range); self.link_tracks.toggled.connect(lambda v:setattr(self.timeline,'linked',v)); self.leave_gap.toggled.connect(lambda v:setattr(self.timeline,'leave_gap',v)); lower_layout.addWidget(self.timeline)
        self.timeline.selectionDragged.connect(self.select)
        self.timeline.cadenceRequested.connect(lambda a,b:self.change_cadence(span=(a,b)))
        self.viewer.scrubActiveChanged.connect(self.timeline.set_external_scrubbing)
        self.viewer.scrubActiveChanged.connect(lambda active:None if active else self.end_scrub())
        self.timeline.scrubStarted.connect(self.begin_scrub); self.timeline.scrubFinished.connect(self.end_scrub)
        self.timeline.drawingMoved.connect(lambda a,b,d:self.edit_drawing_timeline('move',a,b,d)); self.timeline.drawingResized.connect(lambda a,b,c:self.edit_drawing_timeline('resize',a,b,c)); self.timeline.drawingDelete.connect(lambda a,b:self.edit_drawing_timeline('delete',a,b))
        self.timeline_scroll=QScrollBar(Qt.Orientation.Horizontal); self.timeline_scroll.hide(); self.timeline_scroll.valueChanged.connect(self.scroll_timeline); self.timeline.viewportChanged.connect(self.sync_timeline_scroll); lower_layout.addWidget(self.timeline_scroll)
        self.timeline_panel=lower; split.addWidget(lower); split.setStretchFactor(0,1); split.setStretchFactor(1,0); split.setSizes([590,210])
        self.build_library(); self.make_panels_movable(); self.build_comparison(); self.drawing=DrawController(self)
        from clip_geometry import GeometryTools
        self.clip_tools=GeometryTools(self)

    def action(self,menu,text,fn,shortcut=None):
        from ui_text import source,language
        title='Undo' if language()=='en' and source(menu.title())=='Édition' and text=='Annuler' else tr(text)
        a=QAction(title,self); a.setProperty('sourceText',text); a.triggered.connect(fn)
        if shortcut: a.setShortcut(QKeySequence(shortcut))
        from ui_text import source
        menu.addAction(tr(a)); self.addAction(tr(a)); self.action_registry[source(menu.title())+'/'+text]=(a,shortcut or ''); return a
    def build_menus(self):
        file=self.menuBar().addMenu(tr('Fichier'))
        self.action(file,'Nouveau montage',self.new_project,'Ctrl+N'); self.action(file,'Ouvrir des vidéos…',self.open_video,'Ctrl+O'); self.action(file,'Ouvrir un projet…',self.open_project,'Ctrl+Shift+O')
        self.action(file,'Capturer l’écran…',lambda:self.capture_screen(False),'Ctrl+Shift+R')
        self.action(file,'Démarrer / arrêter la capture',lambda:self.capture_screen(True),'Ctrl+Shift+F8')
        self.action(file,'Enregistrer',self.save_project,'Ctrl+S'); self.action(file,'Enregistrer sous…',lambda:self.save_project(True),'Ctrl+Shift+S')
        self.action(file,'Associer les vidéos et projets à cette version',self.associate_files); self.action(file,'Exporter…',self.export_dialog,'Ctrl+E'); file.addSeparator(); self.action(file,'Dossier du cache',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(cache_root())))); file.addSeparator(); self.action(file,'Quitter',self.close,'Alt+F4')
        edit=self.menuBar().addMenu(tr('Édition'))
        self.undo_action=self.action(edit,'Annuler',self.undo,'Ctrl+Z'); self.redo_action=self.action(edit,'Rétablir',self.redo,'Ctrl+Y')
        self.action(edit,'Insérer un vide…',self.insert_gap_dialog,'Ctrl+Shift+G'); self.action(edit,'Couper les images',self.cut_selection,'Ctrl+X'); self.action(edit,'Copier les images',self.copy_selection,'Ctrl+C'); self.action(edit,'Coller les images',self.paste_selection,'Ctrl+V'); self.action(edit,'Supprimer les images',self.delete_selection,'Delete'); self.action(edit,'Tout sélectionner',self.select_all,'Ctrl+A'); self.action(edit,'Effacer la sélection / quitter le plein écran',self.escape,'Escape')
        edit.removeAction(self.action_registry['Édition/Insérer un vide…'][0])
        playback=self.menuBar().addMenu(tr('Lecture'))
        for text,fn,key in [('Lecture / pause',self.toggle_play,'Space'),('Image précédente',lambda:self.step(-1),'Left'),('Image suivante',lambda:self.step(1),'Right'),('Début',lambda:self.seek(0),'Home'),('Fin',lambda:self.seek(self.doc.state.length),'End'),('Marquer entrée',self.mark_in,'I'),('Marquer sortie',self.mark_out,'O')]: self.action(playback,text,fn,key)
        for title in ('Marquer entrée','Marquer sortie'): playback.removeAction(self.action_registry['Lecture/'+title][0])
        self.action(playback,'Clé précédente',lambda:self.step_key(-1),','); self.action(playback,'Clé suivante',lambda:self.step_key(1),'.')
        view=self.menuBar().addMenu(tr('Affichage'))
        self.timeline_action=self.action(view,'Afficher la timeline',lambda checked:self.set_panel('timeline',checked),'Ctrl+2'); self.timeline_action.setCheckable(True); self.timeline_action.setChecked(True)
        self.panel_actions={'timeline':self.timeline_action}
        for key,title,shortcut in [('header','Afficher le bandeau supérieur','Ctrl+3'),('transport','Afficher les commandes de lecture','Ctrl+5'),('timecode','Afficher le time code','Ctrl+6')]:
            action=self.action(view,title,lambda checked,k=key:self.set_panel(k,checked),shortcut); action.setCheckable(True); action.setChecked(True); self.panel_actions[key]=action
        self.library_action=self.action(view,'Afficher la liste de lecture',lambda checked:self.library.setVisible(checked),'Ctrl+8'); self.library_action.setCheckable(True)
        self.library.visibilityChanged.connect(self.sync_library_action)
        panel=self.action(view,'Afficher les réglages de comparaison',lambda checked:self.set_panel('comparison',checked),'Ctrl+9'); panel.setCheckable(True); self.panel_actions['comparison']=panel
        self.layout_action=self.action(view,'Modifier la disposition des panneaux',self.set_layout_editable); self.layout_action.setCheckable(True)
        self.reset_layout_action=self.action(view,'Réinitialiser la disposition des panneaux',self.reset_panel_layout)
        self.action(file,'Options…',self.edit_shortcuts)
        self.action(view,'Réinitialiser le canvas',self.reset_canvas,'0'); self.action(view,'Zoom vidéo +',lambda:self.viewer.zoom_by(1.2),'+'); self.action(view,'Zoom vidéo −',lambda:self.viewer.zoom_by(1/1.2),'-'); self.action(view,'Toute la timeline',self.timeline.reset_view,'Ctrl+0')
        view.removeAction(self.action_registry['Affichage/Toute la timeline'][0])
        self.action(view,'Plein écran vidéo',self.toggle_fullscreen,'F11')
        self.action(view,'Timecode / frames',lambda:self.timeline.set_units('frames' if self.timeline.units=='time' else 'time'),'T')
        self.hflip_action=self.action(view,'Flop - miroir horizontal',lambda:self.toggle_flip('flip_h'),'H'); self.hflip_action.setCheckable(True)
        self.vflip_action=self.action(view,'Flip - miroir vertical',lambda:self.toggle_flip('flip_v'),'Shift+V'); self.vflip_action.setCheckable(True)
        self.comparison_menu(); self.drawing.menus()
        from tool_icons import tool_icon
        self.edit_toolbar=QDockWidget(tr('Outils d’édition'),self); self.edit_toolbar.setObjectName('edit_tools_panel')
        self.edit_toolbar.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea|Qt.DockWidgetArea.RightDockWidgetArea)
        self.edit_tool_buttons=QToolBar(self.edit_toolbar); self.edit_tool_buttons.setOrientation(Qt.Orientation.Vertical)
        self.edit_tool_buttons.setMovable(False); self.edit_tool_buttons.setFloatable(False)
        tools_scroll=QScrollArea(); tools_scroll.setFrameShape(QFrame.Shape.NoFrame); tools_scroll.setWidgetResizable(True)
        tools_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tools_scroll.setWidget(self.edit_tool_buttons); tools_scroll.setMinimumWidth(48)
        self.edit_toolbar.setWidget(tools_scroll)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,self.edit_toolbar)
        self.splitDockWidget(self.edit_toolbar,self.library,Qt.Orientation.Horizontal)
        self.splitDockWidget(self.library,self.comparison_panel,Qt.Orientation.Vertical)
        for action in self.drawing.tool_actions.values(): self.edit_tool_buttons.addAction(tr(action))
        self.edit_tool_buttons.addSeparator()
        for title,mode,key in [('Transformer la sélection ou le clip','resize','Ctrl+T'),('Recadrer le clip','crop','Alt+C')]:
            a=self.action(self.drawing.tools_menu,title,lambda checked=False,m=mode:self.clip_tools.activate(m),key)
            a.setIcon(tool_icon(mode)); self.edit_tool_buttons.addAction(tr(a))
        self.action(self.drawing.tools_menu,'Réinitialiser le cadrage du clip',self.clip_tools.reset)
        self.toolbar_action=self.action(view,'Afficher la barre d’outils',lambda checked:self.edit_toolbar.setVisible(checked)); self.toolbar_action.setCheckable(True); self.toolbar_action.setChecked(True)
        self.panel_actions['tools']=self.toolbar_action
        self.action(view,'Options des modes Lecture / Édition…',lambda:self.workspaces.configure())
        self.action(view,'Mode Lecture / Édition',lambda:self.workspaces.switch('read' if self.workspaces.mode=='edit' else 'edit'))

        for key,panel in self.panel_widgets().items():
            if isinstance(panel,QDockWidget) or panel is self.timecode_overlay: panel.visibilityChanged.connect(lambda visible,k=key:self.sync_panel_action(k,visible))
        helpmenu=self.menuBar().addMenu(tr('Aide')); self.action(helpmenu,'Guide rapide',self.help); self.action(helpmenu,'Dossier des journaux',self.open_logs); self.action(helpmenu,'Rechercher des mises à jour…',self.check_updates); self.action(helpmenu,'À propos',self.about)
        from sync3d import install as install_sync3d
        install_sync3d(self)
        from menu_layout import organize_menus
        organize_menus(self)
        from navigation_modes import install
        install(self)
        if not WINDOWS:
            unavailable={'Capturer l’écran…','Démarrer / arrêter la capture','Associer les vidéos et projets à cette version','Rechercher des mises à jour…'}
            for key,(action,shortcut) in self.action_registry.items():
                if key.startswith('Synchronisation 3D/') or key.split('/',1)[-1] in unavailable:
                    action.setEnabled(False)
                    action.setToolTip(tr('Cette fonction n’est pas encore disponible sous Linux.'))

    def createPopupMenu(self):
        from menu_layout import panel_menu
        return panel_menu(self)

    def apply_preferences(self,data):
        previous=getattr(self,'preferences',{}).get('preview_quality','native')
        self.preferences=data
        from ui_style import set_tooltips_enabled
        set_tooltips_enabled(data.get('tooltips',True))
        from cache_ram import default_cache_mb,MIB
        self.frame_cache.set_budget(data.get('ram_cache_mb',default_cache_mb())*MIB)
        for key,(action,default) in self.action_registry.items(): action.setShortcut(QKeySequence(data['shortcuts'].get(key,default)))
        self.viewer.controls=data['canvas']; self.viewer.scrub_pixels=data['scrub_pixels']
        self.viewer.setToolTip(tr(''))
        if hasattr(self,'scrub_audio'): self.scrub_audio.set_enabled(data.get('scrub_audio',True))
        if previous!=data.get('preview_quality','native') and (self.doc.media or self.reference_sources): self.rebuild_previews()
    def rebuild_previews(self):
        if self.job: return
        self.drawing.finish(); quality=self.preferences['preview_quality']
        entries=[('doc',key,m,self.doc.fps) for key,m in self.doc.media.items()]+[('ref',key,m,Fraction(m['fps'])) for key,m in self.reference_sources.items() if m.get('available') is not False]
        selected=self.compare_media['id'] if self.compare_media else None
        def prepare(progress,cancel):
            result={}; cached={}
            for index,(group,key,m,fps) in enumerate(entries):
                identity=(m['path'],fps,json.dumps(m.get('cadence'),sort_keys=True))
                if identity not in cached:
                    cached[identity]=prepare_media(m['path'],fps,lambda value,message:progress((index+value)/len(entries),message),cancel,quality=quality,cadence=m.get('cadence'),defer_audio=True)
                result[group,key]=dict(cached[identity],id=key)
            return result
        def apply(result):
            for (group,key),m in result.items():
                (self.doc.media if group=='doc' else self.reference_sources)[key]=m
            self.compare_media=({**self.reference_sources,**self.doc.media}).get(selected)
            self.reference_signature=None; self.viewer.reference_rgb=None; self.rebuild_reference_index()
            self.install_doc(self.doc)
        self.begin_task('Mise à jour des aperçus',prepare,apply)
    def edit_shortcuts(self):
        dialog=ShortcutDialog(self.action_registry,self.preferences,self)
        dialog.shortcutsChanged.connect(self.apply_preferences)
        if dialog.exec():
            self.apply_preferences(dialog.result_data)
    def set_layout_editable(self,enabled):
        self.layout_editable=enabled
        self.setStyleSheet('QMainWindow::separator {background:#11161d;border:0;image:none;width:%dpx;height:%dpx;}'%((6,6) if enabled else (0,0)))
        for dock in list(self.panel_widgets().values())+[self.library]:
            if not isinstance(dock,QDockWidget): continue
            if not enabled and dock.isFloating(): dock.setFloating(False)
            dock.setFeatures((QDockWidget.DockWidgetFeature.DockWidgetClosable|QDockWidget.DockWidgetFeature.DockWidgetMovable|QDockWidget.DockWidgetFeature.DockWidgetFloatable) if enabled else QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
            old=dock.titleBarWidget(); bar=QWidget(dock); bar.setFixedHeight(22 if enabled else 0)
            if enabled:
                row=QHBoxLayout(bar); row.setContentsMargins(4,0,4,0)
                row.addStretch()
                for text,tip,fn in [('↗','Détacher',lambda checked=False,d=dock:d.setFloating(not d.isFloating())),('×','Masquer',lambda checked=False,d=dock:d.hide())]:
                    b=QToolButton(bar); b.setText(tr(text)); b.setToolTip(tr(tip)); b.clicked.connect(fn); row.addWidget(b)
            dock.setTitleBarWidget(bar)
            if old: old.deleteLater()
        self.compact_playback_panels()

    def compact_playback_panels(self):
        for dock in (self.header,self.transport_widget):
            dock.setMinimumHeight(0); dock.setMaximumHeight(16777215)
            dock.setFixedHeight(dock.sizeHint().height())

    def reset_panel_layout(self):
        self.workspaces.reset()

    def sync_library_action(self,visible):
        if not self.video_fullscreen:
            with QSignalBlocker(self.library_action): self.library_action.setChecked(visible)
    def make_panels_movable(self):
        self.setDockNestingEnabled(True)
        self.setDockOptions(self.dockOptions() & ~QMainWindow.DockOption.AnimatedDocks)
        old=self.takeCentralWidget(); self.viewer.setParent(self)
        central=QWidget(); layout=QVBoxLayout(central); layout.setContentsMargins(8,8,8,8); layout.addWidget(self.viewer); self.setCentralWidget(central)
        def dock(attribute,title,area):
            content=getattr(self,attribute); content.setParent(self)
            panel=QDockWidget(tr(title),self); panel.setObjectName(attribute); panel.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas); panel.setWidget(content); self.addDockWidget(area,panel)
            if attribute in ('header','transport_widget'): panel.setMaximumHeight(content.sizeHint().height()+30)
            setattr(self,attribute,panel); return panel
        top=dock('header','Bandeau supérieur',Qt.DockWidgetArea.TopDockWidgetArea)
        transport=dock('transport_widget','Lecture et son',Qt.DockWidgetArea.BottomDockWidgetArea)
        transport.topLevelChanged.connect(self.compact_playback_panels)
        timeline=dock('timeline_panel','Timeline',Qt.DockWidgetArea.BottomDockWidgetArea); self.splitDockWidget(transport,timeline,Qt.Orientation.Vertical)
        self.resizeDocks([top,transport,timeline],[78,42,150],Qt.Orientation.Vertical)
        old.hide(); old.deleteLater()

    def build_library(self):
        self.library=QDockWidget(tr('Liste de lecture et médias'),self); self.library.setObjectName('library'); self.library.setMinimumWidth(180)
        box=QWidget(); col=QVBoxLayout(box); tabs=QTabWidget(); self.library_tabs=tabs; self.playlist=QListWidget(); self.media_list=QListWidget(); tabs.addTab(self.playlist,tr('Lecture')); tabs.addTab(self.media_list,tr('Médias')); col.addWidget(tabs)
        box.setMinimumHeight(60); tabs.setMinimumHeight(40)
        self.library.setWidget(box); self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,self.library); self.library.hide(); self.library_signature=None
        self.playlist.itemDoubleClicked.connect(self.play_list_item); self.media_list.itemDoubleClicked.connect(self.seek_media)
        for listing in (self.playlist,self.media_list):
            listing.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection); listing.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); listing.customContextMenuRequested.connect(lambda point,w=listing:self.library_context(w,point))
    def library_context(self,listing,point):
        item=listing.itemAt(point)
        if not item: return
        if not item.isSelected(): listing.setCurrentItem(item)
        self.library_tabs.setCurrentIndex(0 if listing is self.playlist else 1)
        menu=QMenu(tr(listing)); menu.addAction(tr('Supprimer'),self.remove_library_media)
        menu.addSeparator(); cadence=menu.addAction(tr('Changer la cadence…'))
        if listing is self.media_list:
            keys={selected.data(Qt.ItemDataRole.UserRole) for selected in listing.selectedItems()}
            cadence.setEnabled(any(self.doc.media[key].get('has_video',True) for key in keys)); cadence.triggered.connect(lambda:self.change_cadence(keys=keys))
        else:
            spans=[selected.data(Qt.ItemDataRole.UserRole) for selected in listing.selectedItems()]
            cadence.triggered.connect(lambda:self.change_cadence(spans=spans))
        if listing is self.media_list:
            references=[self.doc.media[listing.item(row).data(Qt.ItemDataRole.UserRole)] for row in range(listing.count()) if listing.item(row).isSelected() and self.doc.media[listing.item(row).data(Qt.ItemDataRole.UserRole)].get('has_video',True)]
            if references: menu.addAction(tr('Ajouter aux références B'),lambda:self.set_reference_sequence(references,append=True))
        menu.exec(listing.mapToGlobal(point))
    def change_cadence(self,keys=None,span=None,spans=None):
        if self.job: return
        from cadence_change import plan_ranges,build_change
        from cadence_dialog import CadenceDialog
        ranges=plan_ranges(self.doc.state,self.doc.media,keys,span)
        if spans is not None: ranges=sorted({entry for selected in spans for entry in plan_ranges(self.doc.state,self.doc.media,span=selected)})
        if not ranges: return
        self._resume_after_scrub=False; self.pause(); self.drawing.finish(); self.commit_exposure()
        dialog=CadenceDialog(self,ranges)
        if not dialog.exec(): dialog.deleteLater(); return
        target,mode,pitch=dialog.values(); dialog.deleteLater()
        document=self.doc; state=document.state; quality=self.preferences.get('preview_quality','native')
        def prepare(progress,cancel): return build_change(state,document.media,document.fps,ranges,target,mode,pitch,quality,progress,cancel)
        def apply(result):
            changed,media=result; document.media=media
            document.commit('Changer la cadence',changed); self.library_signature=None; self.refresh(); self.request_frame()
        self.begin_task('Changement de cadence',prepare,apply)
    def sync_timeline_scroll(self):
        if not hasattr(self,'timeline_scroll'): return
        t=self.timeline; maximum=max(0,round((t.state.length if t.state else 0)-t.span()))
        with QSignalBlocker(self.timeline_scroll):
            self.timeline_scroll.setRange(0,maximum); self.timeline_scroll.setPageStep(max(1,round(t.span()))); self.timeline_scroll.setValue(round(t.view_start))
        self.timeline_scroll.setVisible(maximum>0)
        # The tracks have fixed drawing coordinates: extra height belongs to the viewer.
        panel=self.timeline_panel.widget() if isinstance(self.timeline_panel,QDockWidget) else self.timeline_panel
        panel.layout().invalidate()
        panel.setFixedHeight(panel.layout().sizeHint().height())
    def scroll_timeline(self,value): self.timeline.view_start=value; self.timeline.clamp_view(); self.timeline.update()
    def delete_media_range(self,a,b):
        if self.job: return
        self.pause(); self.commit_exposure(); self.doc.select(a,b)
        if self.timeline.selection_track=='drawing': self.edit_drawing_timeline('delete',*self.doc.selected()); return
        if self.doc.delete(): self.refresh(); self.request_frame()

    def refresh_library(self):
        signature=(self.doc.state.segments,self.doc.state.audio)
        if signature==self.library_signature: return
        self.library_signature=signature; self.playlist.clear(); self.media_list.clear(); at=0
        for i,seg in enumerate(self.doc.state.segments):
            key=seg.media if seg.media is not None else locate(self.doc.state.audio,at)[0]
            name=self.doc.media.get(key,{}).get('name','N/A')
            item=QListWidgetItem(f'{i+1}. {name} · {seg.length} '+tr('images')); item.setData(Qt.ItemDataRole.UserRole,(at,at+seg.length)); self.playlist.addItem(item); at+=seg.length
        keys=list(dict.fromkeys(s.media for s in self.doc.state.segments+self.doc.state.audio if s.media is not None))
        for key in keys:
            item=QListWidgetItem(self.doc.media[key]['name']); item.setToolTip(self.doc.media[key]['path']); item.setData(Qt.ItemDataRole.UserRole,key); self.media_list.addItem(tr(item))
    def play_list_item(self,item):
        a,b=item.data(Qt.ItemDataRole.UserRole); self.seek(a); self.select(a,b); self.toggle_play()
    def seek_media(self,item):
        key=item.data(Qt.ItemDataRole.UserRole); at=0
        for track in (self.doc.state.segments,self.doc.state.audio):
            at=0
            for seg in track:
                if seg.media==key: self.seek(at); return
                at+=seg.length
    def remove_library_media(self):
        if self.job: return
        playlist_mode=self.library_tabs.currentIndex()==0
        items=(self.playlist if playlist_mode else self.media_list).selectedItems()
        if not items: return
        self.pause(); self.commit_exposure()
        if playlist_mode:
            changed=self.doc.delete_ranges([item.data(Qt.ItemDataRole.UserRole) for item in items])
        else: changed=self.doc.remove_media_keys([item.data(Qt.ItemDataRole.UserRole) for item in items])
        if changed:
            self.refresh(); self.request_frame(); self.notify('Élément retiré du montage. Fichier original conservé. Ctrl+Z pour annuler.')
    def master_volume(self,*args):
        value=0 if self.volume.muted else self.volume.value()/100
        self.transport.set_volume(value); self.scrub_audio.set_volume(value)

    def split_cursor(self,track='video'):
        if self.job: return
        self.pause(); self.commit_exposure()
        if self.doc.split_at(self.doc.state.position,'linked' if self.link_tracks.isChecked() else track): self.refresh(); self.request_frame()
    def mute_range(self,a,b,track):
        if self.job: return
        self.pause(); self.commit_exposure()
        if self.doc.mute_range(a,b,track): self.refresh(); self.request_frame()

    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
    def dropEvent(self,event):
        paths=[url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths: self.drop_paths(paths); event.acceptProposedAction()
    def sync_panel_action(self,key,visible):
        if not self.video_fullscreen or key=='timecode':
            with QSignalBlocker(self.panel_actions[key]): self.panel_actions[key].setChecked(visible)
    def set_panel(self,name,visible):
        if not self.video_fullscreen or name=='timecode':
            self.panel_widgets()[name].setVisible(visible)
    def panel_widgets(self):
        return {'timeline':self.timeline_panel,'header':self.header,'transport':self.transport_widget,'timecode':self.timecode_overlay,'comparison':self.comparison_panel,'drawing':self.drawing.panel,**({'tools':self.edit_toolbar} if hasattr(self,'edit_toolbar') else {})}
    def set_drawings_linked(self,enabled):
        self.doc.commit('Liaison dessins / vidéo',replace(self.doc.state,drawings_linked=bool(enabled))); self.refresh()
    def edit_drawing_timeline(self,operation,*args):
        if self.job: return
        self.pause(); self.drawing.finish()
        method={'move':self.doc.move_drawings,'resize':self.doc.resize_drawing,'delete':self.doc.delete_drawings}[operation]
        if method(*args): self.refresh(); self.request_frame()
    def duplicate_section(self,a,b,destination=-1):
        if self.job: return
        self.pause(); self.commit_exposure()
        if self.doc.duplicate_range(a,b,None if destination<0 else destination):
            self.refresh(); self.request_frame(); self.notify('Média dupliqué avec sa vidéo et son audio. Annulable avec Ctrl+Z.')
    def move_section(self,a,b,destination,track):
        if self.job: return
        self.pause(); self.commit_exposure()
        if self.doc.move_range(a,b,destination,'linked' if self.link_tracks.isChecked() else track,self.leave_gap.isChecked()):
            self.refresh(); self.request_frame(); self.notify('Section déplacée. Ctrl+Z pour annuler.')
    def delete_track_range(self,a,b,track):
        if self.job: return
        self.pause(); self.commit_exposure()
        if self.doc.delete_track_range(a,b,track):
            self.refresh(); self.request_frame()
            self.notify('Plage supprimée sans décalage ; remplacée par N/A. Ctrl+Z pour annuler.')

    def insert_gap_dialog(self):
        if self.job or not self.doc.media: return
        frames,ok=QInputDialog.getInt(self,tr('Insérer un vide'),tr('Durée en images (noir vidéo + silence) :'),round(float(self.doc.fps)),1,1000000)
        if ok:
            self.pause(); self.commit_exposure(); self.doc.insert_gap(frames); self.refresh(); self.request_frame()
    def associate_files(self):
        if not WINDOWS: return
        try:
            from association import register
            register()
            self.notify('Association enregistrée pour cet utilisateur Windows.')
            QMessageBox.information(self,tr('Associations Windows'),tr('Cette version est enregistrée pour les vidéos et les projets Cadence. Choisissez Cadence dans les applications par défaut de Windows.'))
            QDesktopServices.openUrl(QUrl('ms-settings:defaultapps'))
        except Exception as error: self.error(str(error))
    def toggle_flip(self,axis):
        if self.job or self.editing_text(): return
        self.commit_exposure()
        self.doc.commit('Miroir horizontal' if axis=='flip_h' else 'Miroir vertical',replace(self.doc.state,**{axis:not getattr(self.doc.state,axis)})); self.refresh()
    def reset_canvas(self):
        if self.job or self.editing_text(): return
        self.viewer.reset_view()
        if self.doc.state.flip_h or self.doc.state.flip_v:
            self.commit_exposure()
            self.doc.commit('Réinitialiser les miroirs',replace(self.doc.state,flip_h=False,flip_v=False)); self.refresh()
    def escape(self):
        if self.clip_tools.mode: self.clip_tools.cancel(); return
        if self.drawing.size_drag or self.drawing.text_drag or self.drawing.stroke or self.drawing.selection.indices or self.drawing.selection.gesture: self.drawing.cancel(); return
        if self.video_fullscreen: self.toggle_fullscreen()
        else: self.clear_selection()
    def toggle_fullscreen(self):
        self.setUpdatesEnabled(False)
        try:
            if not self.video_fullscreen:
                self.before_fullscreen={k:not w.isHidden() for k,w in self.panel_widgets().items()}
                self.normal_dock_state=self.saveState(); self.normal_geometry=self.geometry()
                self.normal_margins=self.centralWidget().layout().contentsMargins()
                self.library_was_visible=self.library.isVisible(); self.was_maximized=self.isMaximized()
                self.video_fullscreen=True; self.library.hide(); self.centralWidget().layout().setContentsMargins(0,0,0,0)
                for key,widget in self.panel_widgets().items():
                    if key!='timecode': widget.hide()
                self.menuBar().hide()
                self.showFullScreen()
            else:
                self.showMaximized() if self.was_maximized else self.showNormal()
                if not self.was_maximized: self.setGeometry(self.normal_geometry)
                self.restoreState(self.normal_dock_state)
                self.centralWidget().layout().setContentsMargins(self.normal_margins)
                self.menuBar().show(); self.library.setVisible(self.library_was_visible)
                for key,widget in self.panel_widgets().items(): widget.setVisible(self.before_fullscreen[key] if key!='timecode' else not widget.isHidden())
                self.video_fullscreen=False; self.sync_library_action(self.library_was_visible)
            self.layout().activate()
        finally:
            self.setUpdatesEnabled(True); self.update()
    def drop_paths(self,paths):
        if len(paths)==1 and paths[0].lower().endswith('.cadence'): self.open_project(paths[0])
        else: self.append_paths(paths)
    def append_paths(self,paths):
        if self.job or not paths: return
        self.pause(); self.commit_exposure()
        existing=bool(self.doc.media); rate=self.doc.fps if existing else None
        quality=self.preferences.get('preview_quality','native')
        def prepare(p,c): return prepare_batch(paths,rate,p,c,quality=quality,defer_audio=True)
        def success(items):
            if not existing: self.doc=Document(Fraction(items[0]['fps']))
            self.doc.append_media(items); self.install_doc(self.doc)
            self.notify('Médias ajoutés dans l’ordre de sélection. Cadence harmonisée avec le projet ; audio lié.')
        self.begin_task('Ajout de médias',prepare,success)

    def editing_text(self): return isinstance(QApplication.focusWidget(),(QLineEdit,QAbstractSpinBox))
    def notify(self,text): self.last_notice=text; logging.info(text)
    def error(self,text):
        text=str(text).strip() or 'Erreur sans message. Consulter le journal cadence.log dans le dossier des préférences.'
        logging.error(text,exc_info=sys.exc_info()[0] is not None); QMessageBox.warning(self,tr('Cadence'),tr(text))
    def open_logs(self):
        from diagnostics import log_directory
        path=log_directory(); path.mkdir(parents=True,exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
    def confirm_discard(self):
        self.commit_exposure()
        if not self.doc.dirty: return True
        from dialogs import ConfirmationDialog
        first=next((self.doc.media[s.media] for s in self.doc.state.segments+self.doc.state.audio if s.media in self.doc.media),None)
        title=Path(self.doc.project_path).stem if self.doc.project_path else first['name'] if first else tr('Nouveau montage')
        box=ConfirmationDialog(self,title,tr('Enregistrer les modifications avant de continuer ?'),cancel=True)
        choice=box.exec(); box.deleteLater()
        if choice==0: return False
        if choice==1: return self.save_project()
        return True

    def begin_task(self,title,fn,success):
        if self.job: return
        self.pause(); self.dialog=QProgressDialog(tr(title),tr('Annuler'),0,100,self); self.dialog.setWindowTitle(tr('Cadence')); self.dialog.setWindowModality(Qt.WindowModality.WindowModal); self.dialog.setMinimumDuration(0); self.dialog.setAutoClose(False); self.dialog.setAutoReset(False); self.dialog.setValue(0)
        self.dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._task_progress_value=0.
        task=Task(fn,self); self.job=task
        self.dialog.canceled.connect(task.cancel.set)
        task.progress.connect(lambda p,m:self.task_progress(p,m))
        def result(value):
            if self.dialog: self.dialog.close(); self.dialog=None
            success(value)
        def failed(text):
            if self.dialog: self.dialog.close(); self.dialog=None
            self.error(text)
        def cancelled():
            if self.dialog: self.dialog.close(); self.dialog=None
            self.notify('Opération annulée.')
        task.result.connect(result); task.failed.connect(failed); task.cancelled.connect(cancelled)
        task.finished.connect(lambda:self.finish_task(task)); task.start()
    def task_progress(self,p,m):
        dialog = self.dialog
        if dialog is None:
            return
        from progress_values import bounded_progress
        value=bounded_progress(p,getattr(self,'_task_progress_value',0.),'Qt task_progress')
        self._task_progress_value=value
        percent=int(value*100)
        logging.info('Task progress: value=%r type=%s normalized=%r percent=%r percent_type=%s message=%r',p,type(p).__name__,value,percent,type(percent).__name__,m)
        dialog.setLabelText(tr(m))
        # A modal setValue() processes events: completion may clear self.dialog.
        # Keep this last and never touch the dialog after event processing.
        dialog.setValue(percent)
    def finish_task(self,task):
        self.job=None; task.deleteLater(); self.refresh()

    def new_project(self):
        if not self.job and self.confirm_discard():
            self.install_doc(Document()); self.timeline.reset_view(); self.viewer.reset_view()
    def capture_screen(self,quick=False):
        if not WINDOWS: return
        if self.job: return
        if getattr(self,'capture_dialog',None):
            d=self.capture_dialog
            if d.proc or d.countdown: d.stop()
            else: d.begin()
            return
        self.pause()
        from capture import CaptureDialog
        dialog=CaptureDialog(self); self.capture_dialog=dialog
        if dialog.run(quick=quick)==QDialog.DialogCode.Accepted and dialog.output:
            self.append_paths([dialog.output])
        self.capture_dialog=None; dialog.deleteLater()
    def open_video(self):
        if self.job: return
        paths,_=QFileDialog.getOpenFileNames(self,tr('Ouvrir des médias'),'',tr('Médias (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.mpg *.mpeg *.mts *.gif *.wav *.mp3);;Audio (*.wav *.mp3);;Tous les fichiers (*)'))
        if paths: self.append_paths(paths)
    def open_path(self,path):
        if self.job: return
        if str(path).lower().endswith('.cadence'): self.open_project(path); return
        if not self.confirm_discard(): return
        def success(media):
            doc=Document(Fraction(media['fps'])); doc.append_media([media]); doc.undo_stack.clear(); doc.saved_signature=doc.signature(); self.install_doc(doc)
            self.notify('Média prêt. Glissez sur la vidéo pour scrubber ; Maj + glissez sur la timeline pour sélectionner.')
        quality=self.preferences.get('preview_quality','native')
        self.begin_task('Préparation du média',lambda p,c:prepare_media(path,progress=p,cancel=c,quality=quality,defer_audio=True),success)
    def install_doc(self,doc):
        self.scrub_audio.close()
        self.drawing.cancel(); self.timeline.selection_track='video'; self.clipboard_kind='media'
        changing_doc=doc is not self.doc
        self.pause(); self.doc=doc; self.follow_position=None; self.token+=1; self.display_frame=-1; self.viewer.clear(); self.timeline.wave={}
        for key,m in doc.media.items():
            try:
                if m.get('waveform'): self.timeline.wave[key]=display_waveform(np.load(m['waveform'],allow_pickle=False))
            except (OSError,ValueError): pass
        if changing_doc: self.restore_comparison(doc)
        self.exp_pending=doc.state.exposure; self.refresh(); self.request_frame()
        self.audio_jobs.set_media(doc.media.values())
    def audio_preparation_status(self,text):
        self.audio_progress.setText(text); self.audio_progress.setVisible(bool(text))
    def prepared_audio(self,data):
        for key,media in self.doc.media.items():
            if media.get('audio')!=data['audio']: continue
            media['audio_pending']=False; media['waveform']=data['waveform']
            try: self.timeline.wave[key]=display_waveform(np.load(data['waveform'],allow_pickle=False))
            except (OSError,ValueError): logging.exception('Audio waveform unavailable: %s',data['path'])
        self.timeline.update()
    def open_project(self,path=None):
        if self.job: return
        if not path:
            path,_=QFileDialog.getOpenFileName(self,tr('Ouvrir un projet'),'',tr('Projet Cadence (*.cadence)'))
        if not path or not self.confirm_discard(): return
        quality=self.preferences.get('preview_quality','native')
        def load(p,c):
            doc=Document.load(path)
            for key,m in list(doc.media.items()):
                validate_media(m)
                refreshed=prepare_media(m['path'],doc.fps,p,c,quality=quality,cadence=m.get('cadence'),defer_audio=True)
                refreshed['id']=key; doc.media[key]=refreshed
            from reference_sequence import restore
            restore(doc,quality,p,c)
            return doc
        self.begin_task('Ouverture du projet',load,self.install_doc)
    def save_project(self,save_as=False):
        if self.job or not self.doc.media: return False
        self.drawing.finish(); self.commit_exposure(); path=None if save_as else self.doc.project_path
        if not path:
            from export_dialog import default_destination
            try: suggested=Path(self.doc.project_path) if self.doc.project_path else default_destination(self.doc).with_suffix('.cadence')
            except (OSError,ValueError) as error: self.error(str(error)); return False
            path,_=QFileDialog.getSaveFileName(self,tr('Enregistrer sous…' if save_as else 'Enregistrer'),str(suggested),tr('Projet Cadence (*.cadence)'))
        if not path: return False
        if not path.lower().endswith('.cadence'): path+='.cadence'
        try: self.doc.review=self.comparison_snapshot(); self.doc.save(path); self.refresh(); self.notify('Projet enregistré. Les médias source doivent rester disponibles.'); return True
        except Exception as e: self.error(str(e)); return False
    def export_dialog(self):
        if self.job or not self.doc.state.length: return
        self.pause(); self.commit_exposure()
        from export_dialog import ExportDialog
        try: dialog=ExportDialog(self,self.doc)
        except (OSError,ValueError) as error: self.error(str(error)); return
        try:
            if dialog.exec()==QDialog.DialogCode.Accepted:
                self.start_export(dialog.selectedFiles()[0])
        finally: dialog.deleteLater()
    def start_export(self,path):
        state=self.doc.state if self.drawing.export.isChecked() else replace(self.doc.state,drawings=()); media=dict(self.doc.media); fps=self.doc.fps; use_ev=self.apply_export.isChecked()
        onion=(self.drawing.before.value(),self.drawing.after.value(),self.drawing.ghost.value()/100) if self.drawing.onion.isChecked() else None
        self.begin_task('Export du montage',lambda p,c:export_video(state,media,fps,path,use_ev,p,c,onion),lambda out:self.export_done(out))
    def export_done(self,path):
        self.notify(f'Export terminé : {path}')
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).resolve().parent)))

    def refresh(self):
        st=self.doc.state; n=st.length
        first=next((self.doc.media[s.media] for s in st.segments+st.audio if s.media in self.doc.media),None)
        title=Path(self.doc.project_path).stem if self.doc.project_path else first['name'] if first else tr('Nouveau montage')
        self.setWindowTitle(('● ' if self.doc.dirty else '')+'Cadence - '+title)
        self.timeline.set_document(st,self.doc.media,self.doc.fps)
        self.timeline.drawing_clipboard_length=self.doc.drawing_clipboard_length if self.doc.drawing_clipboard else 0
        with QSignalBlocker(self.link_drawings): self.link_drawings.setChecked(st.drawings_linked)
        self.viewer.position=st.position
        frame=max(0,min(st.position,max(0,n-1)))
        self.timecode_overlay.set_frame(st.position,n,self.doc.fps)
        self.update_media_info(frame)
        for b in (self.export_btn,self.play_btn,self.exp_spin): b.setEnabled(n>0)
        self.sync_loop_button()
        for obj in (self.undo_action,): obj.setEnabled(bool(self.doc.undo_stack))
        for obj in (self.redo_action,): obj.setEnabled(bool(self.doc.redo_stack))
        with QSignalBlocker(self.exp_spin): self.exp_spin.setValue(st.exposure)
        self.viewer.flip_h=st.flip_h; self.viewer.flip_v=st.flip_v
        self.hflip_action.setChecked(st.flip_h); self.vflip_action.setChecked(st.flip_v)
        self.clip_tools.sync(); self.viewer.set_exposure(st.exposure)
        self.refresh_library(); self.refresh_reference_choices(); self.drawing.refresh()

    def update_media_info(self,frame):
        st=self.doc.state
        key=locate(st.segments,min(frame,st.length-1))[0] if st.length else None
        media=self.doc.media.get(key)
        if media is None and st.length: media=self.doc.media.get(locate(st.audio,min(frame,st.length-1))[0])
        text=f'{media["width"]} × {media["height"]} · {float(self.doc.fps):.3f} i/s' if media and media.get('has_video',True) else tr('Audio') if media else '-'
        if self.media_info.text()!=text: self.media_info.setText(tr(text))

    def request_frame(self):
        self.clip_tools.sync()
        self.drawing.refresh()
        if self.doc.state.position!=getattr(self,'follow_position',None):
            self.timeline.ensure_visible(self.doc.state.position); self.follow_position=self.doc.state.position
        if not self.doc.state.length: self.viewer.clear(); self.display_frame=-1; return
        frame=min(self.doc.state.position,self.doc.state.length-1)
        key,idx=locate(self.doc.state.segments,frame)
        self.token+=1; self.display_frame=frame; self.prepare_reference_frame(frame)
        offset=0; muted=False; segment_number=0
        for segment_number,seg in enumerate(self.doc.state.segments):
            if offset<=frame<offset+seg.length: muted=seg.muted; break
            offset+=seg.length
        if key is None or muted:
            first=next((m for m in self.doc.media.values() if m.get('has_video',True)),{'width':1280,'height':720}); w=640; h=max(2,round(w*first['height']/first['width']))
            self.frame_ready(self.token,np.zeros((h,w,3),dtype=np.uint8))
        else:
            from media import prefetch_frames
            ahead=prefetch_frames(self.doc.media[key],idx,seg.start,seg.end,self.frame_cache.budget,backward=not self.transport.running)
            following=self.doc.state.segments[segment_number+1:segment_number+2]
            for next_seg in following:
                if next_seg.media is not None and not next_seg.muted:
                    ahead.extend((self.doc.media[next_seg.media],i) for i in range(next_seg.start,min(next_seg.end,next_seg.start+3)))
            self.decoder.request(self.token,self.doc.media[key],idx,ahead)
    def frame_ready(self,token,arr):
        if token==self.token and not self.comparison_a_ready(token,arr): self.viewer.set_frame(arr); self.rendered_token=token
    def frame_failed(self,token,msg):
        if token==self.token: self.pause(); self.notify('Décodage : '+msg)
    def seek(self,index,audition=False):
        if self.job: return
        self.pause(stop_scrub=not audition); self.play_completed=False; self.doc.state=replace(self.doc.state,position=max(0,min(int(index),self.doc.state.length)))
        self.refresh_position(); self.request_frame()
        if audition: self.scrub_audio.request(self.doc.state,self.doc.media,self.doc.fps,self.doc.state.position)
    def begin_scrub(self):
        self._scrub_document=self.doc; self._resume_after_scrub=self.transport.running; self.pause()
    def end_scrub(self):
        resume=getattr(self,'_resume_after_scrub',False); self._resume_after_scrub=False
        document=getattr(self,'_scrub_document',None); self._scrub_document=None
        if resume and document is self.doc and not self.job and not self.transport.running:
            self.toggle_play()
    def timeline_seek(self,index):
        self.doc.state=replace(self.doc.state,selection=None,loop_range=None); self.selection_anchor=None
        self.seek(index,audition=True)
    def refresh_position(self):
        st=self.doc.state; self.timeline.state=st; self.timeline.update(); self.viewer.position=st.position
        self.timecode_overlay.set_frame(st.position,st.length,self.doc.fps)
        self.update_media_info(min(st.position,max(0,st.length-1)))
    def step(self,amount):
        if self.editing_text(): return
        n=self.doc.state.length
        if n:
            pos=self.doc.state.position
            self.seek((pos+amount)%n if pos<n else (0 if amount>0 else n-1),audition=True)
    def step_key(self,amount):
        if self.key_step: self.step(amount)
        else: self.drawing.navigate(amount)
    def select(self,a,b,position=None):
        self.pause(stop_scrub=position is None); self.play_completed=False; self.doc.select(a,b); self.doc.state=replace(self.doc.state,position=a if position is None else position,loop_range=None); self.refresh_position(); self.request_frame()
        if position is not None: self.scrub_audio.request(self.doc.state,self.doc.media,self.doc.fps,position)
    def select_all(self):
        if self.editing_text(): return
        self.select(0,self.doc.state.length)
    def clear_selection(self,stop_scrub=True):
        self.pause(stop_scrub=stop_scrub); self.doc.state=replace(self.doc.state,selection=None,loop_range=None); self.selection_anchor=None; self.refresh_position(); self.drawing.refresh()
    def mark_in(self):
        if self.editing_text() or not self.doc.state.length: return
        self.selection_anchor=min(self.doc.state.position,self.doc.state.length-1)
        self.select(self.selection_anchor,self.selection_anchor+1)
    def mark_out(self):
        if self.editing_text() or not self.doc.state.length: return
        a=self.selection_anchor if self.selection_anchor is not None else (self.doc.state.selection[0] if self.doc.state.selection else 0)
        b=min(self.doc.state.position,self.doc.state.length-1)
        self.select(min(a,b),max(a,b)+1)
    def set_loop_range(self):
        if self.doc.state.selection:
            self.pause(); self.doc.state=replace(self.doc.state,loop_range=self.doc.state.selection,position=self.doc.state.selection[0]); self.refresh(); self.request_frame(); self.notify('Plage de lecture définie en orange.')
    def clear_loop_range(self): self.pause(); self.doc.state=replace(self.doc.state,loop_range=None); self.refresh()

    def cut_selection(self):
        if self.editing_text() or self.job: return
        self.pause(); self.drawing.finish(); self.commit_exposure()
        if self.timeline.selection_track=='drawing':
            self.drawing.edit_clipboard('cut'); return
        self.clipboard_kind='media'
        count=self.doc.cut(self.copy_audio.isChecked())
        if count:
            self.refresh(); self.request_frame()
            self.notify(f'{count} images coupées ; Ctrl+V pour coller.'+(' Son conservé dans le presse-papiers.' if self.copy_audio.isChecked() else ' Collage sans son selon l’option Copier/coller le son.'))

    def copy_selection(self):
        if self.editing_text() or self.job: return
        if self.timeline.selection_track=='drawing':
            self.drawing.edit_clipboard('copy'); return
        self.clipboard_kind='media'
        count=self.doc.copy(self.copy_audio.isChecked()); self.refresh(); self.notify(f'{count} images copiées'+(' avec leur audio.' if self.copy_audio.isChecked() else ' sans audio.'))
    def delete_selection(self):
        if self.editing_text() or self.job: return
        if self.drawing.edit_objects('delete'): return
        self.pause(); self.commit_exposure()
        if self.timeline.selection_track=='drawing': self.edit_drawing_timeline('delete',*self.doc.selected()); return
        if self.doc.delete(): self.refresh(); self.request_frame(); self.notify('Plage supprimée ; vidéo et audio raccordés.')
    def paste_selection(self):
        if self.editing_text() or self.job: return
        self.pause(); self.commit_exposure()
        if self.clipboard_kind=='drawing':
            self.drawing.edit_clipboard('paste')
            return
        if self.doc.paste(self.copy_audio.isChecked()): self.refresh(); self.request_frame(); self.notify('Images insérées avant la tête de lecture.'+(' Audio du presse-papiers conservé.' if self.copy_audio.isChecked() else ' Plage audio silencieuse.'))
    def undo(self):
        if self.editing_text() or self.job: return
        self.pause(); self.commit_exposure()
        if self.doc.undo(): self.exp_pending=self.doc.state.exposure; self.refresh(); self.request_frame()
    def redo(self):
        if self.editing_text() or self.job: return
        self.pause()
        if self.doc.redo(): self.exp_pending=self.doc.state.exposure; self.refresh(); self.request_frame()
    def exposure_spin(self,value):
        self.exp_pending=value
        self.viewer.set_exposure(value)
        if not self.exp_spin.scrubbing: self.exp_timer.start()
        else: self.exp_timer.stop()
    def commit_exposure(self):
        self.exp_timer.stop()
        if hasattr(self,'exp_spin') and self.doc.media and self.exp_pending != self.doc.state.exposure:
            self.doc.exposure(self.exp_pending); self.refresh()
    def set_exposure(self,value): self.exp_pending=value; self.commit_exposure()
    def sync_loop_button(self):
        with QSignalBlocker(self.loop_btn): self.loop_btn.setChecked(self.playback_mode=='loop')
        self.loop_btn.setSymbol('loop' if self.playback_mode=='loop' else 'once')
        self.loop_btn.setToolTip(tr('Boucle - cliquer pour une lecture unique' if self.playback_mode=='loop' else 'Lecture unique - cliquer pour boucler'))
    def set_loop(self,enabled):
        self.playback_mode='loop' if enabled else 'once'
        self.transport.set_loop(enabled); self.sync_loop_button()
    def toggle_play(self):
        self._resume_after_scrub=False
        self.scrub_audio.stop()
        if self.editing_text() or self.job: return
        if self.transport.running:
            position,_,_=self.transport.clock(); self.doc.state=replace(self.doc.state,position=position)
            self.transport.hold(); self.timer.stop(); self.play_btn.setSymbol('play')
        elif self.transport.suspended:
            self.transport.resume(); self.timer.start(); self.play_btn.setSymbol('pause')
        elif self.doc.state.length:
            self.commit_exposure()
            if self.play_completed:
                self.doc.state=replace(self.doc.state,position=(self.doc.state.selection or self.doc.state.loop_range or (0,0))[0]); self.play_completed=False
            try:
                self.transport.start(self.doc.state,self.doc.media,self.doc.fps,self.playback_mode,1); self.play_btn.setSymbol('pause'); self.timer.start()
                if not self.transport.has_audio_device: self.notify('Aucune sortie audio compatible : lecture vidéo seule.')
            except Exception as e: self.pause(); self.error(str(e))
    def pause(self,*args,stop_scrub=True):
        if stop_scrub: self.scrub_audio.stop()
        if self.transport.running:
            position,_,_=self.transport.clock(); self.doc.state=replace(self.doc.state,position=position)
        self.timer.stop(); self.transport.stop()
        if hasattr(self,'play_btn'): self.play_btn.setSymbol('play')
    def tick(self):
        if not self.transport.running: return
        frame,passnum,done=self.transport.clock()
        # Let the pending frame complete instead of invalidating every slow decode.
        # Seeking still replaces requests immediately; playback catches up to its audio clock.
        if not done and self.rendered_token!=self.token: return
        if frame!=self.doc.state.position or self.display_frame!=frame:
            self.doc.state=replace(self.doc.state,position=frame)
            self.timeline.set_document(self.doc.state,self.doc.media,self.doc.fps); self.viewer.position=frame
            self.timecode_overlay.set_frame(frame,self.doc.state.length,self.doc.fps); self.update_media_info(frame); self.request_frame()
        if done:
            self.pause(); self.doc.state=replace(self.doc.state,position=frame); self.refresh(); self.play_completed=True
    def check_updates(self):
        from update_ui import manager
        manager(self,VERSION).check_now()
    def about(self):
        from dialogs import ButtonStyle
        from PySide6.QtGui import QShortcut
        box=QDialog(self); box.setWindowTitle(tr('Cadence')); box.setMinimumWidth(400)
        layout=QVBoxLayout(box); layout.setContentsMargins(24,20,24,18); layout.setSpacing(18)
        content=QLabel(tr(f'Cadence {VERSION}\nLecteur et éditeur vidéo open source.\nLicence GNU GPLv3 uniquement.\nPython / C++ / Qt / PyAV / FFmpeg.'))
        content.setAlignment(Qt.AlignmentFlag.AlignCenter); content.setTextFormat(Qt.TextFormat.PlainText); layout.addWidget(content)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok); buttons.setCenterButtons(True); buttons.accepted.connect(box.accept); layout.addWidget(buttons)
        box.button_style=ButtonStyle('Fusion'); box.button_style.setParent(box)
        button=buttons.button(QDialogButtonBox.StandardButton.Ok); button.setText('&OK'); button.setStyle(box.button_style); button.setDefault(True)
        shortcut=QShortcut(QKeySequence('O'),box); shortcut.setAutoRepeat(False); shortcut.activated.connect(button.click)
        box.exec(); box.deleteLater()
    def help(self):
        guide=QDialog(self); guide.setWindowTitle(tr('Guide rapide - Cadence')); guide.resize(850,650)
        layout=QVBoxLayout(guide); browser=QTextBrowser(); layout.addWidget(browser)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close); buttons.rejected.connect(guide.reject); layout.addWidget(buttons)
        from dialogs import ButtonStyle
        from PySide6.QtGui import QShortcut
        guide.button_style=ButtonStyle('Fusion'); guide.button_style.setParent(guide); buttons.setCenterButtons(True)
        close_button=buttons.button(QDialogButtonBox.StandardButton.Close); close_button.setText('&'+tr('Fermer')); close_button.setStyle(guide.button_style)
        close_shortcut=QShortcut(QKeySequence(tr('Fermer')[0]),guide); close_shortcut.setAutoRepeat(False); close_shortcut.activated.connect(close_button.click)
        from guide import fill_browser
        fill_browser(browser,self.action_registry)
        guide.exec(); guide.deleteLater()
    def closeEvent(self,e):
        if self.job:
            self.job.cancel.set(); self.notify('Annulation en cours ; fermez la fenêtre une fois terminée.'); e.ignore(); return
        if not getattr(self,'_update_close_approved',False) and not self.confirm_discard(): e.ignore(); return
        if hasattr(self,'update_manager'): self.update_manager.stop()
        self.sync3d.stop()
        self.audio_jobs.stop()
        if self.viewer.graphics_startup is not None: self.viewer.graphics_startup.cancel()
        from playback_preferences import save
        self.playback_prefs_timer.stop(); save(self)
        self.pause(); self.session.close()
        if hasattr(self,'workspaces'):
            if self.video_fullscreen: self.toggle_fullscreen()
            self.workspaces.capture(); self.workspaces.save()
        QApplication.instance().removeEventFilter(self.background_panel_menu)
        self.capture_hotkey.close(); self.pause(); self.decoder.stop(); self.reference_decoder.stop(); self.frame_cache.clear()
        self.drawing.raster_cache.clear(); self.drawing.cache=None
        if self.viewer.surface is not None: self.viewer.surface.compositor.close()
        self.scrub_audio.close()
        if self.preferences.get('clear_cache_on_exit'):
            from cache_tools import clear_cache
            try: clear_cache()
            except OSError as error: logging.warning('Cache cleanup: %s',error)
        e.accept()


def main():
    from diagnostics import initialize,install_qt_logging,startup_ready
    initialize(); install_qt_logging()
    from video_surface import configure_graphics
    configure_graphics()
    app=QApplication(sys.argv); app.setApplicationName('Cadence'); app.setOrganizationName('CadenceStudio'); app.setStyle('Fusion'); app.setStyleSheet(STYLE)
    def hook(kind,value,tb):
        logging.error('Unhandled exception',exc_info=(kind,value,tb)); QMessageBox.warning(None,tr('Cadence'),tr(str(value).strip() or kind.__name__+' : '+tr('Consulter le journal cadence.log dans le dossier des préférences.')))
    sys.excepthook=hook
    logging.info('Startup imports and Qt: %.3fs',_startup_time.perf_counter()-_STARTUP)
    stamp=_startup_time.perf_counter(); win=MainWindow(); logging.info('Startup window construction: %.3fs',_startup_time.perf_counter()-stamp)
    stamp=_startup_time.perf_counter(); win.show(); logging.info('Startup window show: %.3fs; total Python startup: %.3fs',_startup_time.perf_counter()-stamp,_startup_time.perf_counter()-_STARTUP)
    QTimer.singleShot(0,lambda:startup_ready(_STARTUP))
    from update_ui import manager
    manager(win,VERSION).start()
    if len(sys.argv)>1 and Path(sys.argv[1]).is_file(): QTimer.singleShot(150,lambda:win.open_path(sys.argv[1]))
    else: QTimer.singleShot(150,win.session.offer)
    code=app.exec(); sys.exit(code)

if __name__=='__main__':
    if len(sys.argv)>2 and sys.argv[1] in ('--self-test','--self-test-gpu','--self-test-d3d','--self-test-updates'):
        from smoke import run,run_gpu,run_updates
        if sys.argv[1]=='--self-test-updates': run=run_updates
        elif sys.argv[1]=='--self-test-gpu': run=run_gpu
        elif sys.argv[1]=='--self-test-d3d': run=lambda directory:run_gpu(directory,'direct3d')
        try: run(sys.argv[2])
        except Exception:
            import traceback
            Path(sys.argv[2]).mkdir(parents=True,exist_ok=True)
            (Path(sys.argv[2])/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
            sys.exit(1)
    else: main()
