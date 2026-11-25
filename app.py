# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import time as _startup_time
_STARTUP=_startup_time.perf_counter()
import sys
VERSION='2.0.12'
if __name__=='__main__' and getattr(sys,'frozen',False) and not any(arg.startswith('--self-test') for arg in sys.argv):
    from pathlib import Path
    from maintenance_identity import identify_installed_process
    try: identify_installed_process()
    except OSError:
        import logging
        logging.warning('Maintenance identity could not be registered',exc_info=True)
    from update_store import base_executable,dispatch,startup_ready as update_ready
    installed_exe=base_executable()
    running_exe=Path(sys.executable).resolve()
    if running_exe!=installed_exe and running_exe.parent.name==VERSION:
        from update_install import run_worker
        from update_store import shared_install
        if not shared_install(installed_exe):
            # The old launcher keeps its executable and a lock open until the staged child acknowledges it.
            update_ready(VERSION)
            arguments=sys.argv[1:]
            if arguments[:1]==['--apply-in-place']: arguments=arguments[1:]
            run_worker(installed_exe,VERSION,arguments)
            raise SystemExit(0)
    if installed_exe==running_exe:
        try:
            if dispatch(base_executable(),VERSION,sys.argv[1:]): raise SystemExit(0)
        except (ValueError,OSError):
            import logging
            logging.exception('Starting the original Cadence build')
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
    import os
    if os.environ.get('CADENCE_TRIAL_READY') or os.environ.get('CADENCE_MACHINE_TRIAL')=='1':
        try:
            from PySide6 import QtCore,QtGui,QtWidgets,QtMultimedia
            import av,numpy
        except (ImportError,OSError):
            import logging
            logging.exception('The updated runtime could not start; restoring the previous version')
            raise SystemExit(1)
from ui_text import tr
import logging, sys, json
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
import numpy as np
logging.info('Startup base imports: %.3fs',_startup_time.perf_counter()-_STARTUP)
from PySide6.QtCore import Qt, QTimer, QSignalBlocker, QUrl, QSettings
from PySide6.QtGui import QAction, QKeySequence, QDesktopServices, QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QCheckBox, QFileDialog, QMessageBox, QProgressDialog, QLineEdit, QAbstractSpinBox, QScrollArea, QInputDialog, QDockWidget, QListWidget, QListWidgetItem, QTabWidget, QMenu, QScrollBar, QAbstractItemView, QToolButton, QDialog, QTextBrowser, QDialogButtonBox, QToolBar
logging.info('Startup Qt imports cumulative: %.3fs',_startup_time.perf_counter()-_STARTUP)
from model import Document, locate
from media import prepare_batch, prepare_media, validate_media, export_video, cache_root, Cancelled, display_waveform
from engine import Task, Decoder, Transport
from widgets import Viewer, Timeline, ScrubDoubleSpinBox, VolumeBars, TransportButton
from preferences import load_preferences, ShortcutDialog
from comparison import ComparisonMixin
from draw_ui import DrawController
from PySide6.QtWidgets import QGridLayout

STYLE='''
QMainWindow, QWidget { background:#11161d; color:#dce4ee; font-family:"Segoe UI"; font-size:13px; }
QMainWindow::separator {background:#202932;border:0;image:none;width:6px;height:6px;}
QMainWindow::separator:hover {background:#526971;}
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
QComboBox {combobox-popup:0;}
QComboBox::drop-down {border:0;width:18px;}
QComboBox QAbstractItemView {background:#243040;selection-background-color:#42616b;}
QComboBox QAbstractItemView::item {min-height:24px;}
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
QToolBar#studioTopBar {border:0;padding:0;spacing:0;background:#141a20;}
QFrame#studioTop {background:#141a20;border:0;border-bottom:1px solid #333f4c;}
QFrame#studioView,QFrame#studioRailHead {background:#181f27;border:0;border-bottom:1px solid #2a3440;}
QFrame#studioStage {background:#0c1116;border:0;}
QFrame#studioRail,QFrame#studioRailTools {background:#151c23;border:0;}
QFrame#studioRailRule,QFrame#studioDivider {background:#333f4c;border:0;}
QFrame#studioTimeline {background:#161d25;border-bottom:1px solid #333f4c;border-top:1px solid #40505e;}
QWidget#studioTransport {background:#1b232c;border:0;border-top:1px solid #333f4c;}
#studioTransport QWidget {background:transparent;}
#studioTransport QFrame#studioDivider {background:#333f4c;}
#studioTransport QFrame#studioLibraryContinuation {background:#171e26;border-right:1px solid #333f4c;}
QFrame#studioModes {background:#10161c;border:1px solid #333f4c;border-radius:7px;}
QFrame#studioSegment {background:#10161c;border:1px solid #333f4c;border-radius:5px;}
#studioTop QLabel,#studioView QLabel,#studioTimeline QLabel {background:transparent;}
QLabel#studioBrand {font-size:20px;font-weight:700;color:#e9eef3;}
QLabel#studioProject,QLabel#studioSource,QLabel#studioSection {font-size:13px;font-weight:600;color:#e3eaf1;}
QLabel#studioClock {font-family:Consolas;font-size:16px;font-weight:600;color:#e3eaf1;}
QLabel#studioDetails {font-size:11px;color:#9aaabb;}
QFrame#studioEditing {background:#181f27;border:0;border-bottom:1px solid #333f4c;}
#studioEditing QWidget {background:transparent;color:#e3eaf1;font-size:12px;}
#studioEditing QFrame#studioDivider {background:#333f4c;}
#studioEditing QToolButton,#studioEditing QDoubleSpinBox {background:#202a34;border:1px solid #394654;border-radius:5px;padding:2px 6px;}
#studioEditing QToolButton:hover {background:#2a3542;border-color:#526371;}
#studioEditing QToolButton:pressed {background:#334151;}
#studioEditing QToolButton::menu-indicator {width:0;height:0;}
#studioEditing QCheckBox {spacing:5px;}
#studioEditing QScrollBar:horizontal {height:4px;background:#151c23;}
#studioTop QToolButton,#studioView QToolButton,#studioTimeline QToolButton,#studioRail QToolButton {background:transparent;color:#e3eaf1;border:0;border-radius:5px;padding:2px 4px;}
#studioTop QToolButton:hover,#studioView QToolButton:hover,#studioTimeline QToolButton:hover,#studioRail QToolButton:hover {background:#2a3542;}
#studioTop QToolButton:pressed,#studioView QToolButton:pressed,#studioTimeline QToolButton:pressed,#studioRail QToolButton:pressed {background:#334151;}
#studioTop QToolButton:focus,#studioView QToolButton:focus,#studioTimeline QToolButton:focus,#studioRail QToolButton:focus {border:1px solid #68e0cf;}
#studioTop QToolButton:checked,#studioView QToolButton:checked,#studioTimeline QToolButton:checked,#studioRail QToolButton:checked {background:#244044;color:#68e0cf;}
#studioTop QToolButton#studioMode {font-weight:600;padding:3px 9px;}
#studioTop QToolButton#studioMode:checked {background:#68e0cf;color:#0a2a28;}
#studioTop QToolButton#studioMenuButton {border:1px solid #333f4c;padding:3px 8px;}
#studioSegment QToolButton {font-size:11px;border-radius:3px;padding:1px 6px;}
#studioTop QToolButton::menu-indicator,#studioView QToolButton::menu-indicator {width:0;height:0;}
'''

_ui_assets=(Path(__file__).resolve().parent/'assets').as_posix()
STYLE+=f'''
QCheckBox::indicator:checked {{image:url("{_ui_assets}/studio-check.svg");}}
QComboBox::down-arrow {{image:url("{_ui_assets}/studio-down.svg");width:13px;height:13px;}}
'''

def label(text,name=None):
    obj=QLabel(tr(text))
    if name: obj.setObjectName(name)
    return obj

from media_track_ui import MediaTrackController


from studio_workspace import ViewerWorkspace, WorkspaceDockLayout

class MainWindow(WorkspaceDockLayout,MediaTrackController,ComparisonMixin,QMainWindow):
    def __init__(self):
        from diagnostics import StartupTimer
        startup=StartupTimer()
        super().__init__(); self.doc=Document(); self.token=0; self.job=None; self.dialog=None
        self.task_worker=Task(parent=self)
        self.task_worker.progress.connect(self.task_progress)
        self.task_worker.result.connect(self.task_result)
        self.task_worker.failed.connect(self.task_failed)
        self.task_worker.cancelled.connect(self.task_cancelled)
        self.task_worker.finished.connect(self.finish_task)
        self.task_progress_timer=QTimer(self)
        self.task_progress_timer.setSingleShot(True)
        self.task_progress_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.task_progress_timer.timeout.connect(self.show_task_progress)
        from cache_access import CacheAccess
        self.cache_access=CacheAccess()
        from ui_text import initialize_language
        initialize_language()
        from PySide6.QtCore import QLocale
        self.setLocale(QLocale())
        from ui_style import install_tooltip_delay
        install_tooltip_delay()
        startup.checkpoint('language and styles')
        self.display_frame=-1; self.selection_anchor=None; self.last_pass=1; self.playback_mode='loop'; self.exp_pending=0; self.rendered_token=-1; self.play_completed=False
        self.setAcceptDrops(True)
        from preferences import preference_path
        self.settings=QSettings(str(preference_path().with_name('interface.ini')), QSettings.Format.IniFormat); self.video_fullscreen=False
        self.setWindowIcon(QIcon(str(Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'assets'/'cadence.ico')))
        self.setWindowTitle('Cadence 2.0'); self.resize(1360,890); self.setMinimumSize(640,400)
        from cache_ram import FrameCache
        self.frame_cache=FrameCache()
        from export_sources import SessionVideoSources
        self.export_sources=SessionVideoSources()
        self.transport=Transport(self); self.decoder=Decoder(self,warm_codecs=True); self.decoder.ready.connect(self.frame_ready); self.decoder.failed.connect(self.frame_failed); self.decoder.start()
        from scrub_audio import ScrubAudio
        self.scrub_audio=ScrubAudio(self)
        from audio_jobs import AudioJobs
        self.audio_jobs=AudioJobs(self); self.audio_jobs.ready.connect(self.prepared_audio)
        self.audio_jobs.status.connect(self.audio_preparation_status)
        self.audio_jobs.failed.connect(lambda message:self.error(tr('Préparation audio impossible.')+'\n'+message))
        self.timer=QTimer(self); self.timer.setInterval(10); self.timer.setTimerType(Qt.TimerType.PreciseTimer); self.timer.timeout.connect(self.tick)
        self.exp_timer=QTimer(self); self.exp_timer.setSingleShot(True); self.exp_timer.setInterval(300); self.exp_timer.timeout.connect(self.commit_exposure)
        startup.checkpoint('audio and decoder initialization')
        self.clipboard_kind=None; self.clipboard_token=None; self.action_registry={}; self.build_ui(); startup.checkpoint('panels')
        QApplication.clipboard().dataChanged.connect(self.check_clipboard_owner)
        self.build_menus()
        from studio_chrome import StudioChrome
        self.studio=StudioChrome(self)
        self.preferences=load_preferences(self.action_registry); self.apply_preferences(self.preferences); self.set_layout_editable(False)
        startup.checkpoint('menus and preferences')
        from capture import StopHotkey
        self.capture_dialog=None; self.capture_hotkey=StopHotkey(lambda:self.capture_screen(True))
        self.capture_hotkey.register()
        self.resizeDocks([self.library,self.comparison_panel,self.drawing.panel],[262,262,285],Qt.Orientation.Horizontal)
        from workspace_modes import WorkspaceModes
        self.initial_dock_state=self.saveState()
        self.workspaces=WorkspaceModes(self)
        from hover_transport import HoverTransport
        self.hover_transport=HoverTransport(self)
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
        from file_dialogs import install_file_places
        from dialogs import install_dialog_presentation
        install_file_places()
        install_dialog_presentation()

    def build_ui(self):
        from studio_chrome import build_editing_strip
        self.header=build_editing_strip(self)
        self.viewer=Viewer(); self.viewer.scrub.connect(lambda frame:self.seek(frame,audition=True)); self.viewer.scrubStarted.connect(self.begin_scrub); self.viewer.fileDropped.connect(self.drop_paths); self.viewer.fullscreenRequested.connect(self.toggle_fullscreen); self.viewer.openRequested.connect(self.open_video)
        self.viewer_workspace=ViewerWorkspace(self,self.viewer)
        self.setCentralWidget(self.viewer_workspace)
        transport=QHBoxLayout(); transport.setContentsMargins(0,0,0,4); transport.setSpacing(3); self.transport_center=transport
        self.previous_key_btn=TransportButton('first',lambda:self.drawing.navigate(-1),'transport','Clé précédente'); transport.addWidget(self.previous_key_btn)
        self.previous_frame_btn=TransportButton('previous',lambda:self.step(-1),'transport','Image précédente · ←'); transport.addWidget(self.previous_frame_btn)
        self.play_btn=TransportButton('play',self.toggle_play,'primary','Lecture / pause · Espace'); transport.addWidget(self.play_btn)
        self.next_frame_btn=TransportButton('next',lambda:self.step(1),'transport','Image suivante · →'); transport.addWidget(self.next_frame_btn)
        self.next_key_btn=TransportButton('last',lambda:self.drawing.navigate(1),'transport','Clé suivante'); transport.addWidget(self.next_key_btn)
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
        self.transport_widget.setFixedHeight(48)
        from compact_transport import CompactTransport
        self.compact_transport=CompactTransport(self.transport_widget,left,center,right,self)
        lower=QWidget(); lower_layout=QVBoxLayout(lower); lower_layout.setContentsMargins(0,0,0,0); lower_layout.setSpacing(8)
        self.timeline=Timeline(); self.timeline.seek.connect(self.timeline_seek); self.timeline.selected.connect(self.select); self.timeline.moved.connect(self.move_section); self.timeline.duplicated.connect(self.duplicate_section); self.timeline.deleteRequested.connect(self.delete_track_range); self.timeline.muteRequested.connect(self.mute_range); self.timeline.splitRequested.connect(self.split_cursor); self.timeline.deleteMediaRequested.connect(self.delete_media_range); self.link_tracks.toggled.connect(lambda v:setattr(self.timeline,'linked',v)); self.leave_gap.toggled.connect(lambda v:setattr(self.timeline,'leave_gap',v)); lower_layout.addWidget(self.timeline)
        self.timeline.selectionDragged.connect(self.select)
        self.timeline.clipsPicked.connect(self.pick_clips)
        self.timeline.cadenceRequested.connect(lambda a,b:self.change_cadence(span=(a,b)))
        self.viewer.scrubActiveChanged.connect(self.timeline.set_external_scrubbing)
        self.viewer.scrubActiveChanged.connect(lambda active:None if active else self.end_scrub())
        self.timeline.scrubStarted.connect(self.begin_scrub); self.timeline.scrubFinished.connect(self.end_scrub)
        self.timeline.drawingMoved.connect(lambda a,b,d:self.edit_drawing_timeline('move',a,b,d)); self.timeline.drawingResized.connect(lambda a,b,c:self.edit_drawing_timeline('resize',a,b,c)); self.timeline.drawingDelete.connect(lambda a,b:self.edit_drawing_timeline('delete',a,b))
        self.timeline_scroll_slot=QWidget()
        self.timeline_scroll_slot.setObjectName('timelineScrollSlot')
        from timeline_skin import BASE as timeline_background
        self.timeline_scroll_slot.setStyleSheet(f'#timelineScrollSlot {{background:{timeline_background};}}')
        scroll_row=QHBoxLayout(self.timeline_scroll_slot)
        scroll_row.setContentsMargins(0,0,0,0)
        self.timeline_scroll=QScrollBar(Qt.Orientation.Horizontal)
        policy=self.timeline_scroll.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.timeline_scroll.setSizePolicy(policy)
        self.timeline_scroll.hide()
        self.timeline_scroll.valueChanged.connect(self.scroll_timeline)
        self.timeline.viewportChanged.connect(self.sync_timeline_scroll)
        scroll_row.addWidget(self.timeline_scroll)
        lower_layout.addWidget(self.timeline_scroll_slot)
        self.timeline_panel=lower
        self.build_library(); self.make_panels_movable(); self.build_comparison(); self.drawing=DrawController(self)
        from clip_geometry import GeometryTools
        self.clip_tools=GeometryTools(self)
        self.init_media_tracks()

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
        self.action(playback,'Augmenter le volume',lambda: self.volume_shortcut.adjust(1),'Up')
        self.action(playback,'Diminuer le volume',lambda: self.volume_shortcut.adjust(-1),'Down')
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
        from video_mirror import toggle as toggle_video_mirror
        self.video_mirror_action=self.action(view,'Dupliquer l’image vidéo',lambda checked:toggle_video_mirror(self,checked))
        self.video_mirror_action.setCheckable(True)
        self.action(view,'Timecode / frames',lambda:self.timeline.set_units('frames' if self.timeline.units=='time' else 'time'),'Alt+T')
        self.action(view,'Basculer entre les vues de la timeline',lambda:self.workspaces.set_timeline_simple(not self.timeline.simple),'Alt+Shift+T')
        self.hflip_action=self.action(view,'Flop - miroir horizontal',lambda:self.toggle_flip('flip_h'),'H'); self.hflip_action.setCheckable(True)
        self.vflip_action=self.action(view,'Flip - miroir vertical',lambda:self.toggle_flip('flip_v'),'Shift+V'); self.vflip_action.setCheckable(True)
        self.comparison_menu(); self.drawing.menus()
        from tool_icons import tool_icon
        self.edit_toolbar=QDockWidget(tr('Outils d’édition'),self); self.edit_toolbar.setObjectName('edit_tools_panel')
        self.edit_toolbar.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea|Qt.DockWidgetArea.RightDockWidgetArea)
        tools_scroll=QScrollArea(); tools_scroll.setFrameShape(QFrame.Shape.NoFrame); tools_scroll.setWidgetResizable(True)
        tools_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.edit_toolbar.setWidget(tools_scroll)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,self.edit_toolbar)
        self.splitDockWidget(self.library,self.comparison_panel,Qt.Orientation.Vertical)
        for title,mode,key in [('Transformer la sélection ou le clip','resize','Ctrl+T'),('Recadrer le clip','crop','Alt+C')]:
            a=self.action(self.drawing.tools_menu,title,lambda checked=False,m=mode:self.clip_tools.activate(m),key)
            a.setIcon(tool_icon(mode))
        self.action(self.drawing.tools_menu,'Réinitialiser le cadrage du clip',self.clip_tools.reset)
        self.toolbar_action=self.action(view,'Afficher la barre d’outils',lambda checked:self.edit_toolbar.setVisible(checked)); self.toolbar_action.setCheckable(True); self.toolbar_action.setChecked(True)
        self.panel_actions['tools']=self.toolbar_action
        self.action(view,'Options des modes Lecture / Édition…',lambda:self.workspaces.configure())
        self.action(view,'Mode Lecture / Édition',lambda:self.workspaces.switch('read' if self.workspaces.mode=='edit' else 'edit'))

        for key,panel in self.panel_widgets().items():
            if isinstance(panel,QDockWidget) or panel is self.timecode_overlay: panel.visibilityChanged.connect(lambda visible,k=key:self.sync_panel_action(k,visible))
        helpmenu=self.menuBar().addMenu(tr('Aide')); self.action(helpmenu,'Guide rapide',self.help,'F1'); self.action(helpmenu,'Dossier des journaux',self.open_logs); self.action(helpmenu,'Rechercher des mises à jour…',self.check_updates); self.action(helpmenu,'À propos',self.about)
        from sync3d import install as install_sync3d
        install_sync3d(self)
        from menu_layout import organize_menus
        organize_menus(self)
        from navigation_modes import install
        install(self)

    def createPopupMenu(self):
        from menu_layout import panel_menu
        return panel_menu(self)

    def apply_preferences(self,data):
        previous_language=getattr(self,'preferences',{}).get('language')
        previous=getattr(self,'preferences',{}).get('preview_quality','native')
        self.preferences=data
        from ui_style import set_tooltips_enabled
        set_tooltips_enabled(data.get('tooltips',False))
        self.timeline.marker_hover.set_enabled(data.get('marker_comments_hover',True))
        from cache_ram import default_cache_mb,MIB
        self.frame_cache.set_budget(data.get('ram_cache_mb',default_cache_mb())*MIB)
        for key,(action,default) in self.action_registry.items(): action.setShortcut(QKeySequence(data['shortcuts'].get(key,default)))
        from shortcut_defaults import apply_aliases
        apply_aliases(self.action_registry,data.get('keyboard_layout','QWERTY'))
        self.studio.sync_menu_shortcut()
        self.viewer.controls=data['canvas']; self.viewer.scrub_pixels=data['scrub_pixels']
        self.viewer.setToolTip(tr(''))
        if hasattr(self,'scrub_audio'): self.scrub_audio.set_enabled(data.get('scrub_audio',True))
        if previous_language and previous_language!=data['language']:
            from live_language import retranslate
            retranslate(self,data['language'])
        self.sync_tool_shortcuts()
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
    def toggle_language(self):
        from preferences import save_preferences
        from ui_text import language
        data=dict(self.preferences,language='en' if language()=='fr' else 'fr')
        try: save_preferences(data)
        except OSError as error:
            self.error(str(error)); return
        self.apply_preferences(data)
        if language()!=data['language']:
            from live_language import retranslate
            retranslate(self,data['language'])
            self.sync_tool_shortcuts()
    def sync_tool_shortcuts(self):
        from draw_ui import TOOL_SPECS
        for title,tool,_ in TOOL_SPECS:
            action=self.drawing.tool_actions[tool]
            key=action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            label=tr(title)
            tip=label+' · '+key if key else label
            action.setToolTip(tip)
            self.drawing.tool_buttons[tool].setToolTip(tip)
            self.drawing.tool_buttons[tool].setAccessibleName(label)
            self.studio.rail_buttons[tool].setAccessibleName(label)
    def edit_shortcuts(self, checked=False, *, language_focus=False):
        dialog=ShortcutDialog(self.action_registry,self.preferences,self)
        if language_focus:
            dialog.tabs.setCurrentIndex(0)
            dialog.language.setFocus()
        dialog.shortcutsChanged.connect(self.apply_preferences)
        if dialog.exec():
            self.apply_preferences(dialog.result_data)
    def set_layout_editable(self,enabled):
        if getattr(self,'layout_editable',None)==enabled and self.edit_toolbar.titleBarWidget() is not None:
            return
        self.layout_editable=enabled
        for dock in list(self.panel_widgets().values())+[self.library]:
            if not isinstance(dock,QDockWidget): continue
            dock.setFeatures((QDockWidget.DockWidgetFeature.DockWidgetClosable|QDockWidget.DockWidgetFeature.DockWidgetMovable|QDockWidget.DockWidgetFeature.DockWidgetFloatable) if enabled else QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
            old=dock.titleBarWidget(); bar=QWidget(dock); bar.setFixedHeight(22 if enabled else 0)
            if enabled:
                row=QHBoxLayout(bar); row.setContentsMargins(4,0,4,0)
                row.addStretch()
                for text,tip,fn in [('↗','Détacher',lambda checked=False,d=dock:d.setFloating(not d.isFloating())),('×','Masquer',lambda checked=False,d=dock:d.hide())]:
                    b=QToolButton(bar); b.setText(tr(text)); b.setToolTip(tr(tip)); b.clicked.connect(fn); row.addWidget(b)
            dock.setTitleBarWidget(bar)
            if old: old.deleteLater()
        tools=self.edit_toolbar
        tools.setFixedWidth(max(39,tools.titleBarWidget().minimumSizeHint().width()))
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
        def dock(attribute,title,area):
            content=getattr(self,attribute)
            panel=QDockWidget(tr(title),self); panel.setObjectName(attribute); panel.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas); panel.setWidget(content); self.addDockWidget(area,panel)
            if attribute in ('header','transport_widget'): panel.setMaximumHeight(content.sizeHint().height()+30)
            setattr(self,attribute,panel); return panel
        top=dock('header','Bandeau supérieur',Qt.DockWidgetArea.TopDockWidgetArea)
        transport=dock('transport_widget','Lecture et son',Qt.DockWidgetArea.BottomDockWidgetArea)
        transport.topLevelChanged.connect(self.compact_playback_panels)
        timeline=dock('timeline_panel','Timeline',Qt.DockWidgetArea.BottomDockWidgetArea)
        self.resizeDocks([top,timeline],[78,150],Qt.Orientation.Vertical)

    def build_library(self):
        self.library=QDockWidget(tr('Liste de lecture et médias'),self); self.library.setObjectName('library')
        from library_style import LibraryPages,LibraryTabs,SourceRows,EmptyHint,PANEL_STYLE,panel_heading,panel_strip,style_button
        box=QWidget(); col=QVBoxLayout(box); col.setContentsMargins(0,0,0,0)
        tabs=LibraryPages(); tabs.setDocumentMode(True); tabs.setTabBar(LibraryTabs(self.settings,tabs))
        tabs.setStyleSheet(PANEL_STYLE); self.library_tabs=tabs; col.addWidget(tabs)
        from media_source_drop import MediaSourceDrops, MediaSources
        from timeline_thumbnails import ClipThumbnails
        self.source_previews=ClipThumbnails(self,repaint=False)
        self.playlist=QListWidget(); self.media_list=MediaSources()
        self.media_source_drops=MediaSourceDrops(self)
        for listing,tab,heading in ((self.playlist,'Lecture','Ordre de lecture'),(self.media_list,'Médias','Sources du montage')):
            page=QWidget(); page.setObjectName('studioPage')
            layout=QVBoxLayout(page); layout.setContentsMargins(0,0,0,0); layout.setSpacing(0)
            _,count=panel_heading(panel_strip(layout),tr(heading))
            listing.setItemDelegate(SourceRows(listing,thumbnails=self.source_previews)); layout.addWidget(listing,1)
            listing.empty_hint=EmptyHint(listing,tr('Aucun média dans le montage.'))
            footer=panel_strip(layout,'footer')
            reference=style_button(QPushButton(tr('Utiliser comme référence B')),'refs')
            footer.addWidget(reference); footer.addStretch()
            tabs.addTab(page,tr(tab))
            if listing is self.playlist:
                self.playlist_count=count
                self.playback_reference_button=reference
                reference.clicked.connect(self.add_playback_references)
                listing.itemSelectionChanged.connect(lambda:self.playback_reference_button.setEnabled(bool(self.playback_reference_sources())))
            else:
                self.media_count=count
                self.add_reference_button=reference
                reference.clicked.connect(self.add_selected_references)
                listing.itemSelectionChanged.connect(lambda:self.add_reference_button.setEnabled(bool(self.selected_reference_sources())))
            reference.setEnabled(False)
        box.setMinimumHeight(60); tabs.setMinimumHeight(40)
        # The tab strip updates its label widths as the dock is resized.
        from PySide6.QtWidgets import QLayout
        self.library.layout().setSizeConstraint(QLayout.SetNoConstraint)
        self.library.setMinimumWidth(204)
        self.library.setMinimumHeight(60)
        self.library.setWidget(box); self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,self.library); self.library.hide(); self.library_signature=None
        self.playlist.itemDoubleClicked.connect(self.play_list_item); self.media_list.itemDoubleClicked.connect(self.seek_media)
        from playlist_ui import PlaylistPanel
        self.playlists_panel=PlaylistPanel(self); tabs.addTab(self.playlists_panel,tr('Bibliothèque'))
        for listing in (self.playlist,self.media_list):
            listing.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection); listing.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); listing.customContextMenuRequested.connect(lambda point,w=listing:self.library_context(w,point))
    def playback_reference_sources(self):
        from library_style import MEDIA_ROLE
        keys=(item.data(MEDIA_ROLE) for item in self.playlist.selectedItems())
        return [self.doc.media[key] for key in keys if key in self.doc.media and self.doc.media[key].get('has_video',True)]

    def add_playback_references(self):
        sources=self.playback_reference_sources()
        if sources: self.set_reference_sequence(sources,append=True)

    def selected_reference_sources(self):
        return [self.doc.media[item.data(Qt.ItemDataRole.UserRole)] for item in self.media_list.selectedItems()
                if item.data(Qt.ItemDataRole.UserRole) in self.doc.media and self.doc.media[item.data(Qt.ItemDataRole.UserRole)].get('has_video',True)]

    def add_selected_references(self):
        sources=self.selected_reference_sources()
        if sources: self.set_reference_sequence(sources,append=True)

    def library_context(self,listing,point):
        item=listing.itemAt(point)
        if not item: return
        if not item.isSelected(): listing.setCurrentItem(item)
        self.library_tabs.setCurrentIndex(0 if listing is self.playlist else 1)
        menu=QMenu(listing)
        if listing is self.media_list:
            self.media_source_drops.track_menu(menu)
        menu.addAction(tr('Supprimer'),self.remove_library_media)
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
        menu.exec(listing.viewport().mapToGlobal(point))
        menu.deleteLater()
    def change_cadence(self,keys=None,span=None,spans=None):
        if self.job: return
        from track_cadence import plan_tracks,build_tracks
        from cadence_dialog import CadenceDialog
        plans=plan_tracks(self.doc,keys,span,spans)
        ranges=[entry for track,entries in plans for entry in entries]
        if not ranges: return
        self._resume_after_scrub=False; self.pause(); self.drawing.finish(); self.commit_exposure()
        dialog=CadenceDialog(self,ranges)
        if not dialog.exec(): dialog.deleteLater(); return
        target,mode,pitch=dialog.values(); dialog.deleteLater()
        document=self.doc; state=document.state; quality=self.preferences.get('preview_quality','native')
        def prepare(progress,cancel): return build_tracks(state,document.media,document.fps,plans,target,mode,pitch,quality,progress,cancel)
        def apply(result):
            changed,media=result; document.media=media
            document.commit('Changer la cadence',changed); self.library_signature=None; self.refresh(); self.request_frame()
        self.begin_task('Changement de cadence',prepare,apply)
    def sync_timeline_scroll(self):
        if not hasattr(self,'timeline_scroll'): return
        t=self.timeline; maximum=max(0,round((t.state.length if t.state else 0)-t.span()))
        with QSignalBlocker(self.timeline_scroll):
            self.timeline_scroll.setRange(0,maximum); self.timeline_scroll.setPageStep(max(1,round(t.span()))); self.timeline_scroll.setValue(round(t.view_start))
        self.timeline_scroll_slot.setVisible(not getattr(getattr(self,'studio',None),'collapsed',False))
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
        from library_style import icon,media_details,set_preview,TITLE_ROLE,DETAIL_ROLE,SYMBOL_ROLE,MEDIA_ROLE
        track=self.doc.active_track
        signature=(self.doc.state.tracks,self.doc.active_track_id)
        if signature==self.library_signature: return
        self.library_signature=signature; self.playlist.clear(); self.media_list.clear(); at=0
        for i,seg in enumerate(track.segments):
            key=seg.media if seg.media is not None else locate(track.audio,at)[0]
            name=self.doc.media.get(key,{}).get('name','N/A')
            item=QListWidgetItem(f'{i+1}. {name} · {seg.length} '+tr('images')); item.setData(Qt.ItemDataRole.UserRole,(at,at+seg.length))
            media=self.doc.media.get(key,{})
            item.setData(MEDIA_ROLE,key); item.setData(TITLE_ROLE,name)
            set_preview(item,media,seg.start)
            item.setData(SYMBOL_ROLE,'film' if media.get('has_video',True) else 'wave')
            millis=round(at*1000/self.doc.fps)
            stamp=f'{millis//3600000:02}:{millis//60000%60:02}:{millis//1000%60:02}.{millis%1000:03}'
            item.setData(DETAIL_ROLE,stamp+' · '+f'{float(self.doc.fps):g} '+tr('i/s'))
            item.setToolTip(item.text()); self.playlist.addItem(item); at+=seg.length
        keys=list(dict.fromkeys(s.media for s in self.doc.state.all_segments if s.media is not None))
        keys.sort(key=lambda key:not self.doc.media[key].get('has_video',True))
        for key in keys:
            media=self.doc.media[key]; details=media_details(media)
            item=QListWidgetItem(icon('film' if media.get('has_video', True) else 'wave'),media['name']+('\n'+details if details else ''))
            set_preview(item,media)
            item.setData(SYMBOL_ROLE,'film' if media.get('has_video',True) else 'wave')
            item.setToolTip(media['path']); item.setData(Qt.ItemDataRole.UserRole,key); self.media_list.addItem(item)
        self.playlist_count.setText(str(self.playlist.count())); self.media_count.setText(str(self.media_list.count()))
    def play_list_item(self,item):
        a,b=item.data(Qt.ItemDataRole.UserRole); self.seek(a); self.select(a,b); self.toggle_play()
    def seek_media(self,item):
        key=item.data(Qt.ItemDataRole.UserRole); at=0
        for track in self.doc.state.tracks:
            for segments in (track.segments,track.audio):
                at=0
                for seg in segments:
                    if seg.media==key: self.select_media_track(track.info.id); self.seek(at); return
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
        self.doc.set_track_effect('Miroir horizontal' if axis=='flip_h' else 'Miroir vertical',**{axis:not getattr(self.doc.active_track,axis)}); self.refresh(); self.request_frame()
    def reset_canvas(self):
        if self.job or self.editing_text(): return
        self.viewer.reset_view()
        if any(t.flip_h or t.flip_v for t in self.doc.editable_tracks()):
            self.commit_exposure()
            self.doc.set_track_effect('Réinitialiser les miroirs',flip_h=False,flip_v=False); self.refresh(); self.request_frame()
    def escape(self):
        if self.clip_tools.mode: self.clip_tools.cancel(); return
        if self.drawing.size_drag or self.drawing.text_drag or self.drawing.stroke or self.drawing.selection.indices or self.drawing.selection.gesture: self.drawing.cancel(); return
        if self.video_fullscreen: self.toggle_fullscreen()
        else: self.clear_selection()
    def toggle_fullscreen(self):
        returning_maximized=self.video_fullscreen and self.was_maximized and self.screen()==self.normal_screen
        target = self.normal_geometry.size() if returning_maximized else None
        if not self.video_fullscreen and self.screen():
            target = self.screen().geometry().size()
        with self.studio.change_video_layout(target):
            if not self.video_fullscreen:
                self.before_fullscreen={k:not w.isHidden() for k,w in self.panel_widgets().items()}
                self.normal_dock_state=self.saveState(); self.normal_geometry=self.geometry()
                self.normal_screen=self.screen()
                self.library_was_visible=self.library.isVisible(); self.was_maximized=self.isMaximized()
                self.maximized_return=None
                if self.was_maximized and QApplication.platformName()=='windows':
                    from fullscreen_win import MaximizedReturn
                    self.maximized_return=MaximizedReturn(self)
                self.video_fullscreen=True; self.library.hide()
                self.studio.headers.update_hover()
                for key,widget in self.panel_widgets().items():
                    if key!='timecode': widget.hide()
                self.menuBar().hide()
                self.studio.bar.hide(); self.studio.view.hide(); self.studio.stage_layout.setContentsMargins(0,0,0,0)
                self.showFullScreen()
            else:
                if returning_maximized and self.maximized_return:
                    self.maximized_return.restore(self)
                elif self.was_maximized:
                    self.showMaximized()
                else:
                    self.showNormal()
                self.maximized_return=None
                if not self.was_maximized: self.setGeometry(self.normal_geometry)
                self.restoreState(self.normal_dock_state)
                self.studio.view.show(); self.library.setVisible(self.library_was_visible)
                for key,widget in self.panel_widgets().items(): widget.setVisible(self.before_fullscreen[key] if key!='timecode' else not widget.isHidden())
                self.video_fullscreen=False; self.sync_library_action(self.library_was_visible)
                self.studio.headers.configure(self.workspaces.mode=='read',self.timeline.simple and not self.studio.collapsed)
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
        self.begin_media_open(paths, 'Ajout de médias', prepare, success)

    def editing_text(self):
        focused=QApplication.focusWidget()
        return isinstance(focused,(QLineEdit,QAbstractSpinBox)) or bool(focused and focused.property('canvasTextInput'))
    def keyPressEvent(self,event):
        # Windows keyboard layouts may deliver the printed question mark with Shift still set.
        if event.text()=='?' and event.modifiers()==Qt.ShiftModifier and not self.editing_text():
            question=QKeySequence('?')
            for action,_ in self.action_registry.values():
                if action.isEnabled() and question in action.shortcuts():
                    action.trigger(); event.accept(); return
        super().keyPressEvent(event)
    def notify(self,text): self.last_notice=text; logging.info(text)
    def error(self,text):
        text=str(text).strip() or 'Erreur sans message. Consulter le journal cadence.log dans le dossier des préférences.'
        logging.error(text,exc_info=sys.exc_info()[0] is not None); QMessageBox.warning(self,tr('Cadence'),tr(text))
    def open_logs(self):
        from diagnostics import log_directory
        path=log_directory(); path.mkdir(parents=True,exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
    def confirm_discard(self):
        if self.drawing.text_editor: self.drawing.text_editor.finish(True)
        self.commit_exposure()
        if not self.doc.dirty: return True
        from dialogs import ConfirmationDialog
        first=next((self.doc.media[s.media] for s in self.doc.state.all_segments if s.media in self.doc.media),None)
        title=Path(self.doc.project_path).stem if self.doc.project_path else first['name'] if first else tr('Nouveau montage')
        box=ConfirmationDialog(self,title,tr('Enregistrer les modifications avant de continuer ?'),cancel=True)
        choice=box.exec(); box.deleteLater()
        if choice==0: return False
        if choice==1: return self.save_project()
        return True

    def begin_media_open(self, paths, title, prepare, success, on_error=None):
        self.begin_task(title, prepare, success, progress_delay_ms=1000 if len(paths)==1 else 0, on_error=on_error)

    def begin_task(self,title,fn,success,*,progress_delay_ms=0,on_error=None,on_finished=None):
        if self.job: return
        self.pause()
        self._task_progress_value=0.
        self._task_progress_message=title
        self._task_success=success
        self._task_error=on_error or self.error
        self._task_finished=on_finished
        self.job=self.task_worker
        self.job.start_work(fn)
        if progress_delay_ms:
            self.task_progress_timer.start(progress_delay_ms)
        else:
            self.show_task_progress()
    def show_task_progress(self):
        if not self.job or self.job.isFinished() or self.job.cancel.is_set(): return
        dialog=QProgressDialog(tr(self._task_progress_message),tr('Annuler'),0,100,self)
        self.dialog=dialog
        dialog.setWindowTitle(tr('Cadence'))
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.canceled.connect(self.job.cancel.set)
        dialog.setValue(int(self._task_progress_value*100))
        dialog.show()
    def dismiss_task_progress(self):
        self.task_progress_timer.stop()
        dialog,self.dialog=self.dialog,None
        if dialog is not None:
            dialog.reset()
            dialog.hide()
            dialog.deleteLater()
    def task_result(self,value):
        success=self._task_success
        self.dismiss_task_progress()
        success(value)
    def task_failed(self,text):
        on_error=self._task_error
        self.dismiss_task_progress()
        on_error(text)
    def task_cancelled(self):
        self.dismiss_task_progress()
        self.notify('Opération annulée.')
    def task_progress(self,p,m):
        dialog = self.dialog
        from progress_values import bounded_progress
        value=bounded_progress(p,getattr(self,'_task_progress_value',0.),'Qt task_progress')
        self._task_progress_value=value
        self._task_progress_message=m
        if dialog is None: return
        percent=int(value*100)
        logging.info('Task progress: value=%r type=%s normalized=%r percent=%r percent_type=%s message=%r',p,type(p).__name__,value,percent,type(percent).__name__,m)
        dialog.setLabelText(tr(m))
        # A modal setValue() processes events: completion may clear self.dialog.
        # Keep this last and never touch the dialog after event processing.
        dialog.setValue(percent)
    def finish_task(self):
        self.task_worker.wait()
        callback=self._task_finished
        self.job=self._task_success=self._task_error=self._task_finished=None
        self.refresh()
        if callback: callback()

    def new_project(self):
        if not self.job and self.confirm_discard():
            self.install_doc(Document()); self.timeline.reset_view(); self.viewer.reset_view()
    def capture_screen(self,quick=False):
        if self.job: return
        if getattr(self,'capture_dialog',None):
            d=self.capture_dialog
            if d.armed or d.proc or d.countdown: d.stop()
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
        self.begin_media_open([path], 'Préparation du média',lambda p,c:prepare_media(path,progress=p,cancel=c,quality=quality,defer_audio=True),success)
    def install_doc(self,doc):
        self.export_sources.retain(doc.media.values())
        self.scrub_audio.close()
        self.drawing.cancel(); self.timeline.selection_track='video'
        changing_doc=doc is not self.doc
        if changing_doc:
            self.decoder.release_sources()
            self.reference_decoder.release_sources()
            doc.clear_clipboard()
            if self.clipboard_kind != 'objects': self.release_clipboard()
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
        self.commit_exposure()
        self.drawing.commit_gamma()
        state=self.doc.state if self.drawing.export.isChecked() else replace(self.doc.state,drawings=()); media=dict(self.doc.media); fps=self.doc.fps
        onion=(self.drawing.before.value(),self.drawing.after.value(),self.drawing.ghost.value()/100) if self.drawing.onion.isChecked() else None
        def completed(output):
            from review_panel import offer_rendered_markers
            offer_rendered_markers(self,output,state,fps)
            self.export_done(output)
        self.begin_task('Export du montage',lambda p,c:export_video(state,media,fps,path,True,p,c,onion,self.export_sources),completed)
    def export_done(self,path):
        self.notify(f'Export terminé : {path}')
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).resolve().parent)))

    def refresh(self):
        st=self.doc.state; n=st.length
        self.refresh_media_tracks()
        first=next((self.doc.media[s.media] for s in st.all_segments if s.media in self.doc.media),None)
        title=Path(self.doc.project_path).stem if self.doc.project_path else first['name'] if first else tr('Nouveau montage')
        self.setWindowTitle(('● ' if self.doc.dirty else '')+'Cadence 2.0 - '+title)
        self.studio.update_document(title)
        self.timeline.set_document(st,self.doc.media,self.doc.fps)
        self.sync_timeline_scroll()
        self.timeline.drawing_clipboard_length=self.doc.drawing_clipboard_length if self.doc.drawing_clipboard else 0
        with QSignalBlocker(self.link_drawings): self.link_drawings.setChecked(st.drawings_linked)
        self.viewer.position=st.position
        frame=max(0,min(st.position,max(0,n-1)))
        self.timecode_overlay.set_frame(st.position,n,self.doc.fps)
        self.update_media_info(frame)
        for b in (self.export_btn,self.play_btn,self.exp_spin,self.exposure_button): b.setEnabled(n>0)
        self.sync_loop_button()
        for obj in (self.undo_action,): obj.setEnabled(bool(self.doc.undo_stack))
        for obj in (self.redo_action,): obj.setEnabled(bool(self.doc.redo_stack))
        with QSignalBlocker(self.exp_spin): self.exp_spin.setValue(self.doc.active_track.exposure)
        self.exposure_button.setChecked(self.doc.active_track_id not in dict(st.bypassed_exposures))
        self.viewer.flip_h=st.flip_h if st.second_track is None else False; self.viewer.flip_v=st.flip_v if st.second_track is None else False
        self.hflip_action.setChecked(self.doc.active_track.flip_h); self.vflip_action.setChecked(self.doc.active_track.flip_v)
        self.clip_tools.sync(); self.viewer.set_exposure(st.exposure if st.second_track is None else 0)
        self.refresh_library(); self.refresh_reference_choices(); self.drawing.refresh()
        self.viewer.comparing=self.comparison_active(); self.sync_comparison_controls()

    def update_media_info(self,frame):
        if getattr(self,'reference_track_id',None) and hasattr(self,'track_ref_readout'): self.refresh_track_reference(frame)
        active=self.doc.active_track
        tracks=(active,)+tuple(t for t in self.doc.state.tracks if t.info.id!=active.info.id)
        media=None
        for track in tracks:
            for segments in (track.segments,track.audio):
                if not 0<=frame<sum(s.length for s in segments): continue
                media=self.doc.media.get(locate(segments,frame)[0])
                if media is not None: break
            if media is not None: break
        text=f'{media["width"]} × {media["height"]} · {float(self.doc.fps):.3f} i/s' if media and media.get('has_video',True) else tr('Audio') if media else '-'
        if self.media_info.text()!=text: self.media_info.setText(tr(text))
        if hasattr(self,'studio'): self.studio.update_media(media,self.media_info.text())

    def request_frame(self):
        self.clip_tools.sync()
        self.drawing.refresh()
        if self.doc.state.position!=getattr(self,'follow_position',None):
            self.timeline.ensure_visible(self.doc.state.position); self.follow_position=self.doc.state.position
        if not self.doc.state.length: self.viewer.clear(); self.display_frame=-1; return
        frame=min(self.doc.state.position,self.doc.state.length-1)
        if self.doc.state.second_track is not None:
            from composite_media import frame_layers,canvas_size
            self.token+=1; self.display_frame=frame; self.prepare_reference_frame(frame)
            identities=None
            reference=getattr(self,'reference_track_id',None)
            if self.comparison_active() and reference:
                identities={t.info.id for t in self.doc.state.tracks if t.info.id!=reference}
            self.decoder.request_layers(self.token,frame_layers(self.doc.state,self.doc.media,frame,identities),canvas_size(self.doc.state,self.doc.media))
            return
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
        self.doc.state=replace(self.doc.state,selection=None,selected_clips=(),loop_range=None); self.selection_anchor=None
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
            self.navigate_to((pos+amount)%n if pos<n else (0 if amount>0 else n-1))
    def navigate_to(self,index):
        state=self.doc.state
        if state.selection and not any(start<=index<end for start,end in state.selection_ranges()):
            self.doc.state=replace(state,selection=None,selected_clips=())
            self.selection_anchor=None
        self.seek(index,audition=True)
    def step_key(self,amount):
        if self.key_step: self.step(amount)
        else: self.drawing.navigate(amount)
    def pick_clips(self,ranges,identity,position):
        self.pause(); self.play_completed=False
        tracks=tuple(track.info.id for track in self.doc.state.tracks if any(key==track.info.id for key,a,b in ranges))
        self.doc.selected_track_ids=tracks or (identity,)
        self.doc.active_track_id=identity if identity in self.doc.selected_track_ids else self.doc.selected_track_ids[0]
        ordered=sorted(ranges,key=lambda span:span[1])
        self.doc.state=replace(self.doc.state,selection=tuple(ordered[0][1:]) if ordered else None,
                               selected_clips=tuple(ordered),position=ordered[0][1] if len(ordered)>1 else position,loop_range=None)
        self.refresh(); self.request_frame()

    def select(self,a,b,position=None):
        self.pause(stop_scrub=position is None); self.play_completed=False; self.doc.select(a,b); self.doc.state=replace(self.doc.state,position=a if position is None else position,loop_range=None); self.refresh_position(); self.request_frame()
        self.drawing.comments.refresh()
        if position is not None: self.scrub_audio.request(self.doc.state,self.doc.media,self.doc.fps,position)
    def select_all(self):
        if self.editing_text(): return
        self.select(0,self.doc.state.length)
    def clear_selection(self,stop_scrub=True):
        self.pause(stop_scrub=stop_scrub); self.doc.state=replace(self.doc.state,selection=None,selected_clips=(),loop_range=None); self.selection_anchor=None; self.refresh_position(); self.drawing.refresh()
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

    def claim_clipboard(self,kind):
        from PySide6.QtCore import QMimeData, QUuid
        self.clipboard_kind=kind
        if kind=='objects':
            self.doc.clear_clipboard()
            self.timeline.drawing_clipboard_length=0
        else:
            self.drawing.object_clipboard=()
        self.clipboard_token=QUuid.createUuid().toRfc4122()
        mime=QMimeData()
        mime.setData('application/x-cadence-edit',self.clipboard_token)
        QApplication.clipboard().setMimeData(mime)

    def check_clipboard_owner(self):
        if self.clipboard_token is None: return
        mime=QApplication.clipboard().mimeData()
        if mime is not None and mime.data('application/x-cadence-edit')==self.clipboard_token: return
        self.clipboard_kind=None; self.clipboard_token=None
        self.doc.clear_clipboard()
        self.drawing.object_clipboard=()
        self.timeline.drawing_clipboard_length=0

    def release_clipboard(self):
        self.check_clipboard_owner()
        if self.clipboard_token is not None: QApplication.clipboard().clear()

    def cut_selection(self):
        self.copy_or_cut('cut')

    def copy_selection(self):
        self.copy_or_cut('copy')

    def copy_or_cut(self,operation):
        if self.editing_text() or self.job: return
        if operation=='cut':
            self.pause(); self.drawing.finish(); self.commit_exposure()
        if self.viewer.hasFocus() and self.drawing.edit_objects(operation): return
        if self.timeline.selection_track=='drawing':
            self.drawing.edit_clipboard(operation); return
        audio=self.copy_audio.isChecked()
        count=self.doc.cut(audio) if operation=='cut' else self.doc.copy(audio)
        if not count: return
        self.claim_clipboard('media'); self.refresh()
        if operation=='cut':
            self.request_frame()
            self.notify(f'{count} images coupées ; Ctrl+V pour coller.'+(' Son conservé dans le presse-papiers.' if audio else ' Collage sans son selon l’option Copier/coller le son.'))
        else:
            self.notify(f'{count} images copiées'+(' avec leur audio.' if audio else ' sans audio.'))
    def delete_selection(self):
        if self.editing_text() or self.job: return
        focus=QApplication.focusWidget()
        if focus is self.playlists_panel or (focus and self.playlists_panel.isAncestorOf(focus)):
            if focus is self.playlists_panel.files: self.playlists_panel.remove_files()
            elif focus is self.playlists_panel.tree: self.playlists_panel.remove_selected_entries()
            return
        if self.drawing.edit_objects('delete'): return
        self.pause(); self.commit_exposure()
        if self.timeline.selection_track=='drawing': self.edit_drawing_timeline('delete',*self.doc.selected()); return
        if self.doc.delete(): self.refresh(); self.request_frame(); self.notify('Plage supprimée ; vidéo et audio raccordés.')
    def paste_selection(self):
        if self.editing_text() or self.job: return
        self.check_clipboard_owner()
        if not self.clipboard_kind: return
        self.pause(); self.commit_exposure()
        if self.clipboard_kind=='objects':
            self.drawing.edit_objects('paste')
            return
        if self.clipboard_kind=='drawing':
            self.drawing.edit_clipboard('paste')
            return
        if self.doc.paste(self.copy_audio.isChecked()): self.refresh(); self.request_frame(); self.notify('Images insérées avant la tête de lecture.'+(' Audio du presse-papiers conservé.' if self.copy_audio.isChecked() else ' Plage audio silencieuse.'))
    def undo(self):
        if self.editing_text() or self.job: return
        self.pause(); self.commit_exposure()
        if self.doc.undo(): self.exp_pending=self.doc.active_track.exposure; self.refresh(); self.request_frame()
    def redo(self):
        if self.editing_text() or self.job: return
        self.pause()
        if self.doc.redo(): self.exp_pending=self.doc.active_track.exposure; self.refresh(); self.request_frame()
    def exposure_spin(self,value):
        self.exp_pending=value; self.exp_dirty=True
        if self.doc.state.second_track is None: self.viewer.set_exposure(value)
        else:
            self.viewer.layer_exposures={t.info.id:value for t in self.doc.editable_tracks()}
            self.viewer.apply_effect()
        if not self.exp_spin.scrubbing: self.exp_timer.start()
        else: self.exp_timer.stop()
    def commit_exposure(self):
        self.exp_timer.stop()
        if hasattr(self,'exp_spin') and self.doc.media and getattr(self,'exp_dirty',False):
            self.doc.exposure(self.exp_pending); self.viewer.layer_exposures=None; self.refresh()
            if self.doc.state.second_track is not None: self.request_frame()
        self.viewer.layer_exposures=None
        self.exp_dirty=False
    def set_exposure(self,value): self.exp_pending=value; self.exp_dirty=True; self.commit_exposure()
    def toggle_exposure(self, enabled):
        self.commit_exposure()
        if self.doc.exposure(enabled=enabled):
            self.exp_pending=self.doc.active_track.exposure
            self.refresh()
            if self.doc.state.second_track is not None: self.request_frame()
    def sync_loop_button(self):
        with QSignalBlocker(self.loop_btn): self.loop_btn.setChecked(self.playback_mode=='loop')
        self.loop_btn.setSymbol('loop' if self.playback_mode=='loop' else 'once')
        self.loop_btn.setToolTip(tr('Boucle - cliquer pour une lecture unique' if self.playback_mode=='loop' else 'Lecture unique - cliquer pour boucler'))
    def set_loop(self,enabled):
        self.playback_mode='loop' if enabled else 'once'
        self.transport.set_loop(enabled); self.sync_loop_button()
        if hasattr(self,'playback_prefs_timer'): self.playback_prefs_timer.start()
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
        fill_browser(browser,self.action_registry,self.preferences.get('keyboard_layout','QWERTY'))
        guide.exec(); guide.deleteLater()
    def closeEvent(self,e):
        if self.job:
            self.job.cancel.set(); self.notify('Annulation en cours ; fermez la fenêtre une fois terminée.'); e.ignore(); return
        if not getattr(self,'_update_close_approved',False) and not self.confirm_discard(): e.ignore(); return
        self.release_clipboard()
        if hasattr(self,'update_manager'): self.update_manager.stop()
        self.hover_transport.close()
        if getattr(self,'video_mirror',None): self.video_mirror.close()
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
        QApplication.instance().removeEventFilter(self.volume_shortcut)
        self.capture_hotkey.close(); self.pause(); self.decoder.stop(); self.reference_decoder.stop(); self.frame_cache.clear()
        self.drawing.raster_cache.clear(); self.drawing.cache=None
        if self.viewer.surface is not None: self.viewer.surface.compositor.close()
        self.scrub_audio.close()
        self.export_sources.close()
        if self.preferences.get('clear_cache_on_exit'):
            try: self.cache_access.clean(closing=True)
            except OSError as error: logging.warning('Cache cleanup: %s',error)
        else:
            self.cache_access.close()
        e.accept()


def main():
    from diagnostics import initialize,install_qt_logging,startup_ready
    initialize(); install_qt_logging()
    from video_surface import configure_graphics
    configure_graphics()
    app=QApplication(sys.argv); app.setApplicationName('Cadence 2.0'); app.setOrganizationName('CadenceStudio'); app.setStyle('Fusion'); app.setStyleSheet(STYLE)
    def hook(kind,value,tb):
        logging.error('Unhandled exception',exc_info=(kind,value,tb)); QMessageBox.warning(None,tr('Cadence'),tr(str(value).strip() or kind.__name__+' : '+tr('Consulter le journal cadence.log dans le dossier des préférences.')))
    sys.excepthook=hook
    logging.info('Startup imports and Qt: %.3fs',_startup_time.perf_counter()-_STARTUP)
    stamp=_startup_time.perf_counter(); win=MainWindow(); logging.info('Startup window construction: %.3fs',_startup_time.perf_counter()-stamp)
    stamp=_startup_time.perf_counter(); win.show(); logging.info('Startup window show: %.3fs; total Python startup: %.3fs',_startup_time.perf_counter()-stamp,_startup_time.perf_counter()-_STARTUP)
    QTimer.singleShot(0,lambda:startup_ready(_STARTUP))
    from update_store import startup_ready as confirm_update
    QTimer.singleShot(0,lambda:confirm_update(VERSION))
    from update_ui import manager
    manager(win,VERSION).start()
    if len(sys.argv)>1 and Path(sys.argv[1]).is_file(): QTimer.singleShot(0,lambda:win.open_path(sys.argv[1]))
    else: QTimer.singleShot(150,win.session.offer)
    code=app.exec(); sys.exit(code)

if __name__=='__main__':
    if len(sys.argv)>2 and sys.argv[1] in ('--self-test','--self-test-gpu','--self-test-d3d','--self-test-updates'):
        from smoke import run,run_gpu,run_updates
        if sys.argv[1]=='--self-test-updates': run=run_updates
        elif sys.argv[1]=='--self-test-gpu': run=run_gpu
        elif sys.argv[1]=='--self-test-d3d': run=lambda directory:run_gpu(directory,'direct3d')
        try:
            from PySide6.QtMultimedia import QAudioSink
            from unittest.mock import patch
            set_sink_volume = QAudioSink.setVolume
            with patch.object(QAudioSink, 'setVolume', lambda sink, volume: set_sink_volume(sink, 0.)):
                run(sys.argv[2])
        except Exception:
            import traceback
            Path(sys.argv[2]).mkdir(parents=True,exist_ok=True)
            (Path(sys.argv[2])/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
            sys.exit(1)
    else: main()
