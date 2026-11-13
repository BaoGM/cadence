# SPDX-License-Identifier: GPL-3.0-only
from ui_text import tr
import ctypes, os, subprocess, tempfile, time, uuid, json, threading,math,re,logging
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QRect, QAbstractNativeEventFilter, QEventLoop
from PySide6.QtGui import QPainter,QColor,QPen
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QCheckBox, QFileDialog, QMessageBox, QSystemTrayIcon, QMenu, QLineEdit
from media import ffmpeg
from capture_feedback import CaptureFeedback,RegionOutline,start_sound,recording_icon

class MonitorInfo(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('monitor',wintypes.RECT),('work',wintypes.RECT),
              ('flags',wintypes.DWORD),('device',wintypes.WCHAR*32)]

def monitor_info(handle):
    info=MonitorInfo(); info.size=ctypes.sizeof(info)
    fn=ctypes.windll.user32.GetMonitorInfoW
    fn.argtypes=[wintypes.HMONITOR,ctypes.POINTER(MonitorInfo)]; fn.restype=wintypes.BOOL
    if not fn(handle,ctypes.byref(info)): raise RuntimeError('Écran Windows indisponible.')
    r=info.monitor
    return info.device,(r.left,r.top,r.right-r.left,r.bottom-r.top)

def native_monitors():
    if os.name!='nt': return {}
    result={}
    callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HMONITOR,wintypes.HDC,ctypes.POINTER(wintypes.RECT),wintypes.LPARAM)
    @callback
    def visit(handle,dc,rect,data):
        name,rect=monitor_info(handle); result[name]=rect; return True
    ctypes.windll.user32.EnumDisplayMonitors(None,None,visit,0)
    return result

def physical_region(screen,region,monitors=None):
    g=screen.geometry()
    if monitors is None and os.name!='nt':
        from capture_x11 import monitors as x11_monitors
        monitors=x11_monitors()
    if monitors is None and os.name=='nt':
        _,(x,y,w,h)=monitor_info(int(screen.nativeInterface().handle()))
    else:
        if not monitors or screen.name() not in monitors: raise RuntimeError('Écran indisponible.')
        x,y,w,h=monitors[screen.name()]
    r=region.intersected(QRect(0,0,g.width(),g.height()))
    left=round(r.left()*w/g.width()); top=round(r.top()*h/g.height())
    right=round((r.x()+r.width())*w/g.width()); bottom=round((r.y()+r.height())*h/g.height())
    if right-left<2 or bottom-top<2: raise ValueError('Choisissez une zone de deux pixels minimum.')
    return x+left,y+top,right-left,bottom-top

def capture_args(rect,fps,cursor,path):
    x,y,w,h=rect
    if w<2 or h<2 or fps not in (12,24,25,30,60): raise ValueError('Paramètres de capture invalides.')
    args = ['-hide_banner','-loglevel','warning','-n','-f','gdigrab','-framerate',str(fps),
        '-draw_mouse',str(int(cursor)),'-offset_x',str(x),'-offset_y',str(y),
        '-video_size',f'{w}x{h}','-i','desktop','-an',
        '-vf','pad=ceil(iw/2)*2:ceil(ih/2)*2','-c:v','libx264','-preset','ultrafast',
        '-crf','20','-pix_fmt','yuv420p','-movflags','+faststart',str(path)]
    if os.name!='nt':
        display=os.environ.get('DISPLAY')
        if not display or x<0 or y<0: raise ValueError('Écran X11 indisponible.')
        args[args.index('gdigrab')]='x11grab'
        args[args.index('-offset_x')]='-grab_x'; args[args.index('-offset_y')]='-grab_y'
        args[args.index('desktop')]=display
    if Path(path).suffix.lower()=='.gif':
        args=args[:args.index('-vf')]+['-filter_complex','split[a][b];[a]palettegen=stats_mode=single[p];[b][p]paletteuse=new=1:dither=bayer','-loop','0',str(path)]
    return args

class RegionPicker(QDialog):
    def __init__(self,screen):
        super().__init__(None,Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(screen.geometry()); self.setCursor(Qt.CursorShape.CrossCursor)
        self.anchor=None; self.region=QRect()
    def mousePressEvent(self,e):
        if e.button()==Qt.MouseButton.LeftButton: self.anchor=e.position().toPoint(); self.region=QRect()
    def mouseMoveEvent(self,e):
        if self.anchor is not None:
            self.region=QRect(self.anchor,e.position().toPoint()).normalized().intersected(self.rect()); self.update()
    def mouseReleaseEvent(self,e):
        if e.button()==Qt.MouseButton.LeftButton and self.region.width()>=8 and self.region.height()>=8: self.accept()
    def paintEvent(self,e):
        p=QPainter(self); p.fillRect(self.rect(),QColor(0,0,0,100))
        if not self.region.isEmpty():
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear); p.fillRect(self.region,Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver); p.setPen(QPen(QColor('#68e0cf'),2)); p.drawRect(self.region)
        p.setPen(Qt.GlobalColor.white); p.drawText(25,35,tr('Tracez la zone à enregistrer · Échap pour annuler'))

class StopHotkey(QAbstractNativeEventFilter):
    ID=0xCA12
    def __init__(self,stop):
        super().__init__(); self.stop=stop; self.registered=False
        self.linux=None
    def register(self):
        if self.registered: return True
        if os.name!='nt':
            from capture_x11 import Hotkey
            self.linux=self.linux or Hotkey(self.stop)
            self.registered=self.linux.register()
            return self.registered
        if os.name=='nt':
            self.registered=bool(ctypes.windll.user32.RegisterHotKey(None,self.ID,0x4000|0x2|0x4,0x77)) # Ctrl+Shift+F8
        if self.registered: QApplication.instance().installNativeEventFilter(self)
        return self.registered
    def close(self):
        if self.linux:
            self.linux.close(); self.registered=False; return
        if self.registered:
            ctypes.windll.user32.UnregisterHotKey(None,self.ID)
            QApplication.instance().removeNativeEventFilter(self); self.registered=False
    def nativeEventFilter(self,kind,message):
        msg=wintypes.MSG.from_address(int(message))
        if msg.message==0x312 and msg.wParam==self.ID:
            QTimer.singleShot(0,self.stop); return True,0
        return False,0

class CaptureDialog(QDialog):
    def __init__(self,parent):
        super().__init__(parent); self.setWindowTitle(tr('Capturer l’écran')); self.resize(520,320)
        self.quick=False; self.armed=False; self.proc=None; self.output=None; self.region=None; self.countdown=0; self.stopping=False
        self.feedback=CaptureFeedback(); self.record_ready=threading.Event(); self.start_notified=False
        self.destroyed.connect(self.feedback.deleteLater)
        self.outline=RegionOutline(); self.destroyed.connect(self.outline.deleteLater); self.finished.connect(self.outline.hide)
        from capture_inputs import CaptureInputs
        self.inputs=CaptureInputs(); self.destroyed.connect(self.inputs.deleteLater); self.finished.connect(self.inputs.stop)
        self.audio=None; self.mux_thread=None; self.mux_done=threading.Event(); self.mux_error=None
        self.log=None; self.owns_hotkey=not hasattr(parent,'capture_hotkey'); self.hotkey=getattr(parent,'capture_hotkey',None) or StopHotkey(self.stop); self.saved_state=parent.windowState()
        self.timer=QTimer(self); self.timer.setInterval(200); self.timer.timeout.connect(self.tick)
        root=QVBoxLayout(self)
        self.screens=QComboBox()
        for s in QApplication.screens(): self.screens.addItem(tr(f'{s.name()} · {s.geometry().width()} × {s.geometry().height()}'),s)
        root.addWidget(self.screens); self.screens.currentIndexChanged.connect(self.reset_region)
        self.zone=QPushButton(tr('Tracer une zone…')); self.zone.clicked.connect(self.pick); root.addWidget(self.zone)
        self.full=QPushButton(tr('Utiliser tout l’écran')); self.full.clicked.connect(self.reset_region); root.addWidget(self.full)
        for button in (self.full,self.zone):
            button.setCheckable(True); button.setStyleSheet('QPushButton:checked {background:#355558;border:1px solid #68e0cf;}')
        row=QHBoxLayout(); row.addWidget(QLabel(tr('Images/sec'))); self.fps=QComboBox()
        for n in (12,24,25,30,60): self.fps.addItem(tr(str(n)),n)
        self.fps.setCurrentText('30'); row.addWidget(self.fps); row.addStretch()
        root.addLayout(row)
        row=QHBoxLayout(); row.addWidget(QLabel(tr('Inclure :')))
        self.include_cadence=QCheckBox(tr('Cadence')); self.include_cadence.setToolTip(tr('Décoché : réduire Cadence pendant la capture.'))
        self.include_keyboard=QCheckBox(tr('Clavier'))
        self.include_cursor=QCheckBox(tr('Curseur')); self.include_cursor.setChecked(True)
        self.include_clicks=QCheckBox(tr('Clic'))
        for control in (self.include_cadence,self.include_keyboard,self.include_cursor,self.include_clicks): row.addWidget(control)
        row.addStretch(); root.addLayout(row)
        self.format=QComboBox(); self.format.addItems(tr(['MP4','GIF'])); root.addWidget(self.format)
        row=QHBoxLayout(); row.addWidget(QLabel(tr('Capturer le son :')))
        self.system_audio=QCheckBox(tr('Son de l’ordinateur')); self.microphone=QCheckBox(tr('Microphone'))
        row.addWidget(self.system_audio); row.addWidget(self.microphone); row.addStretch(); root.addLayout(row)
        self.audio_note=QLabel(tr('Le format GIF ne contient pas de son.')); root.addWidget(self.audio_note)
        self.format.currentTextChanged.connect(self.update_audio_options)
        row=QHBoxLayout(); self.folder=QLineEdit(); self.folder.setPlaceholderText(tr('Par défaut : dossier temporaire Windows / Cadence') if os.name=='nt' else tr('Par défaut : dossier temporaire / Cadence'))
        self.browse=QPushButton(tr('Parcourir…')); self.browse.clicked.connect(self.choose_folder)
        row.addWidget(self.folder); row.addWidget(self.browse); root.addLayout(row)
        root.addWidget(QLabel(tr('Démarrer / arrêter la capture : Ctrl+Shift+F8')))
        self.status=QLabel(tr('Écran complet')); self.status.setWordWrap(True); root.addWidget(self.status); self.load_settings()
        self.start=QPushButton(tr('Capturer la vidéo…')); self.start.clicked.connect(self.begin); root.addWidget(self.start)
        self.cancel=QPushButton(tr('Fermer')); self.cancel.clicked.connect(self.reject); root.addWidget(self.cancel)
        self.tray=QSystemTrayIcon(parent.windowIcon(),self); menu=QMenu()
        menu.addAction(tr('Arrêter la capture et ouvrir dans Cadence'),self.stop); self.tray.setContextMenu(menu); self.tray_menu=menu
        self.tray.setToolTip(tr('Cadence · capture en cours · Ctrl+Maj+F8 pour arrêter'))
        self.update_audio_options(); self.update_region_ui()
    def update_audio_options(self):
        enabled=self.format.currentText()=='MP4'
        self.system_audio.setEnabled(enabled); self.microphone.setEnabled(enabled); self.audio_note.setVisible(not enabled)
    def update_region_ui(self):
        self.full.setChecked(self.region is None); self.zone.setChecked(self.region is not None)
        self.status.setText(tr('Écran complet' if self.region is None else f'Zone : {self.region.width()} × {self.region.height()}'))
        self.outline.display(self.screens.currentData(),self.region)
    def release_hotkey(self):
        if self.owns_hotkey: self.hotkey.close()
    def settings_path(self):
        from preferences import preference_path
        return preference_path().with_name('capture.json')
    def choose_folder(self):
        folder=QFileDialog.getExistingDirectory(self,tr('Dossier des captures'),self.folder.text())
        if folder: self.folder.setText(folder)
    def load_settings(self):
        try:
            data=json.loads(self.settings_path().read_text(encoding='utf-8'))
            self.format.setCurrentText(data.get('format','MP4')); self.fps.setCurrentText(str(data.get('fps',30)))
            self.include_cursor.setChecked(bool(data.get('cursor',True))); self.folder.setText(str(data.get('folder','')) if data.get('custom',True) else '')
            self.system_audio.setChecked(data.get('system_audio') is True); self.microphone.setChecked(data.get('microphone') is True)
            self.include_cadence.setChecked(data.get('include_cadence') is True)
            self.include_keyboard.setChecked(data.get('keyboard') is True); self.include_clicks.setChecked(data.get('clicks') is True)
            screen=self.screens.findText(data.get('screen',''))
            if screen>=0: self.screens.setCurrentIndex(screen)
            if data.get('region'): self.region=QRect(*data['region'])
        except (OSError,ValueError,TypeError): pass
    def save_settings(self):
        from preferences import write_file
        write_file(self.settings_path(),dict(format=self.format.currentText(),fps=self.fps.currentData(),cursor=self.include_cursor.isChecked(),
            include_cadence=self.include_cadence.isChecked(),keyboard=self.include_keyboard.isChecked(),clicks=self.include_clicks.isChecked(),
            system_audio=self.system_audio.isChecked(),microphone=self.microphone.isChecked(),folder=self.folder.text().strip(),screen=self.screens.currentText(),region=list(self.region.getRect()) if self.region else None))
    def run(self,quick=False):

        # QDialog.exec exits when hidden. This loop survives hiding during selection/recording.
        loop=QEventLoop(self); self.finished.connect(loop.quit)
        self.quick=quick
        if quick:
            self.setWindowModality(Qt.WindowModality.NonModal)
            QTimer.singleShot(0,self.quick_begin)
        else:
            self.setWindowModality(Qt.WindowModality.ApplicationModal); self.show()
        loop.exec()
        self.finished.disconnect(loop.quit)
        return self.result()
    def quick_begin(self):
        self.begin()
        if not self.armed: self.reject()
        elif not self.include_cadence.isChecked(): self.parentWidget().showMinimized()
    def reset_region(self,*args):
        self.region=None
        if hasattr(self,'status'): self.update_region_ui()
    def pick(self):
        self.outline.hide(); self.hide()
        if not self.include_cadence.isChecked(): self.parentWidget().hide()
        picker=RegionPicker(self.screens.currentData())
        try:
            if picker.exec()==QDialog.DialogCode.Accepted:
                self.region=QRect(picker.region); self.status.setText(tr(f'Zone : {self.region.width()} × {self.region.height()}'))
        finally:
            picker.close(); self.restore(); self.update_region_ui()
    def restore(self):
        self.parentWidget().setWindowState(self.saved_state); self.parentWidget().show()
        if not self.quick: self.show(); self.raise_(); self.activateWindow()
    def begin(self):
        if self.proc or self.countdown or self.mux_thread: return
        screen=self.screens.currentData()
        try: self.rect_px=physical_region(screen,self.region if self.region is not None else QRect(0,0,screen.geometry().width(),screen.geometry().height()))
        except Exception as e: QMessageBox.warning(self,tr('Capture'),tr(str(e))); return
        folder=Path(self.folder.text().strip()) if self.folder.text().strip() else Path(tempfile.gettempdir())/'Cadence'
        try:
            folder.mkdir(parents=True,exist_ok=True)
            self.save_settings()
        except OSError as e: QMessageBox.warning(self,tr('Capture'),tr(str(e))); return
        path=folder/('Capture-'+datetime.now().strftime('%Y-%m-%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]+'.'+self.format.currentText().lower())
        if not self.hotkey.register():
            QMessageBox.warning(self,tr('Capture'),tr('Ctrl+Maj+F8 est indisponible. Libérez ce raccourci dans l’autre application puis réessayez.')); return
        if self.format.currentText()=='MP4' and (self.system_audio.isChecked() or self.microphone.isChecked()):
            try:
                from capture_audio import AudioCapture
                self.audio=AudioCapture(self.system_audio.isChecked(),self.microphone.isChecked())
            except Exception as e:
                self.release_hotkey(); QMessageBox.warning(self,tr('Capture audio'),tr(str(e))); return
        self.armed=True; self.path=Path(path); self.deadline=time.monotonic()+3; self.countdown=3
        self.update_region_ui()
        for widget in (self.start,self.screens,self.zone,self.full,self.fps,self.include_cursor,self.include_cadence,self.include_keyboard,self.include_clicks,self.format,self.system_audio,self.microphone,self.folder,self.browse): widget.setEnabled(False)
        self.cancel.setText(tr('Annuler')); self.timer.start(); self.tick()
    def tick(self):
        if self.mux_thread:
            if self.mux_done.is_set():
                self.mux_thread=None
                if self.mux_error: self.failed('Le son n’a pas pu être ajouté. La vidéo sans son est conservée ici :\n'+str(self.path)+'\n'+self.mux_error)
                else: self.finish_capture()
            return
        if self.countdown:
            remaining=self.deadline-time.monotonic()
            if remaining>0:
                seconds=min(3,max(1,math.ceil(remaining)))
                self.status.setText(tr(f'Démarrage dans {seconds}…')); self.feedback.countdown(self.screens.currentData(),seconds); return
            self.countdown=0; self.feedback.hide(); self.hide()
            if not self.include_cadence.isChecked(): self.parentWidget().showMinimized()
            QTimer.singleShot(350,self.launch); return
        if self.proc:
            code=self.proc.poll()
            if code is not None: self.recording_finished(code); return
            if self.record_ready.is_set() and not self.start_notified and not self.stopping:
                self.start_notified=True; self.tray.setIcon(recording_icon()); self.feedback.recording(self.screens.currentData()); start_sound()
            if self.stopping and time.monotonic()>self.stop_deadline:
                self.status.setText(tr('La finalisation prend du temps. Le fichier reste en cours d’écriture.'))
    def launch(self):
        if not self.armed or not self.hotkey.registered: return
        self.outline.prepare_recording()
        try:
            self.inputs.start(self.screens.currentData(),self.region,self.include_keyboard.isChecked(),self.include_clicks.isChecked())
            self.log=tempfile.TemporaryFile()
            if self.audio: self.audio.start()
            self.video_started=time.time()
            self.record_ready.clear()
            args=capture_args(self.rect_px,self.fps.currentData(),self.include_cursor.isChecked(),self.path); args[args.index('-loglevel')+1]='info'
            self.proc=subprocess.Popen([ffmpeg(),'-progress','pipe:1','-stats_period','0.1','-nostats',*args],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.progress_thread=threading.Thread(target=self.read_progress,args=(self.proc.stdout,),daemon=True); self.progress_thread.start()
            self.started=time.monotonic(); self.tray.show(); self.cancel.setText(tr('Arrêter et ouvrir')); self.status.setText(tr('Enregistrement en cours · Ctrl+Maj+F8 pour arrêter'))
        except Exception as e: self.failed(str(e))
    def read_progress(self,stream):
        try:
            for line in iter(stream.readline,b''):
                key,_,value=line.strip().partition(b'=')
                if key==b'frame':
                    try:
                        if int(value)>0: self.record_ready.set()
                    except ValueError: pass
        finally: stream.close()
    def stop(self):
        self.inputs.stop()
        self.feedback.hide(); self.outline.hide()
        if self.mux_thread: return
        if self.countdown or not self.proc:
            self.countdown=0; self.timer.stop(); self.release_hotkey(); self.restore(); self.reject(); return
        if not self.stopping:
            self.stopping=True; self.stop_deadline=time.monotonic()+30
            self.status.setText(tr('Finalisation de la vidéo…')); self.cancel.setEnabled(False)
            try: self.proc.stdin.write(b'q\n'); self.proc.stdin.flush()
            except (OSError,BrokenPipeError): pass
            self.restore()
    def recording_finished(self,code):
        self.inputs.stop()
        self.armed=False
        self.feedback.hide(); self.outline.hide()
        if hasattr(self,'progress_thread'): self.progress_thread.join(timeout=.2)
        self.release_hotkey(); self.tray.hide()
        self.log.seek(0); log=self.log.read().decode('utf-8',errors='replace'); self.log.close(); self.log=None
        self.proc.stdin.close(); self.proc=None
        if code==0 and self.path.exists() and self.path.stat().st_size>0:
            if self.audio:
                match=re.search(r'start:\s*([\d.]+)',log)
                epoch=float(match[1]) if match else self.video_started
                self.status.setText(tr('Finalisation du son…')); self.cancel.setEnabled(False)
                self.mux_thread=threading.Thread(target=self.finish_audio,args=(epoch,),daemon=True); self.mux_thread.start(); self.timer.start()
            else: self.finish_capture()
        else: self.failed('La capture n’a pas pu être finalisée.\n'+log[-2500:])
    def finish_audio(self,epoch):
        try:
            from capture_audio import mux_audio
            self.audio.stop()
            mux_audio(self.path,self.audio.tracks,epoch)
        except Exception as e: logging.exception('Capture audio mux failed'); self.mux_error=str(e) or type(e).__name__
        finally:
            try: self.audio.close()
            except Exception as e: logging.exception('Capture audio cleanup failed'); self.mux_error=self.mux_error or str(e)
            finally: self.audio=None; self.mux_done.set()
    def finish_capture(self):
        self.timer.stop(); self.output=str(self.path); self.restore(); self.accept()
    def close_audio(self):
        if self.audio and not self.mux_thread:
            try: self.audio.close()
            except Exception: logging.exception('Capture audio cleanup failed')
            finally: self.audio=None
    def failed(self,message):
        self.inputs.stop()
        self.feedback.hide(); self.outline.hide(); self.close_audio()
        self.timer.stop(); self.release_hotkey(); self.tray.hide()
        if self.log: self.log.close(); self.log=None
        self.restore(); QMessageBox.warning(self,tr('Capture'),tr(message)); self.done(QDialog.DialogCode.Rejected)
    def reject(self):
        self.inputs.stop()
        if self.mux_thread: return
        self.armed=False
        self.feedback.hide(); self.outline.hide()
        if self.proc: self.stop(); return
        self.close_audio()
        self.countdown=0; self.timer.stop(); self.release_hotkey(); self.tray.hide(); super().reject()
