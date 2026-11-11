# SPDX-License-Identifier: GPL-3.0-only
from fractions import Fraction
import json
import logging
import os
import secrets
import time

from PySide6.QtCore import QObject, QTimer, QLockFile, Signal
from PySide6.QtNetwork import QHostAddress, QTcpServer, QAbstractSocket

from cadence_change import rounded
from integrations.cadence_bridge import endpoint_path, number
from preferences import preference_path, write_file
from ui_text import tr


def frame_rate(value):
    number(value, 1000)
    if not 1 <= value <= 240:
        raise ValueError('Unsupported frame rate')
    for numerator in (24000, 30000, 48000, 60000, 120000):
        if abs(value - numerator / 1001) < .001:
            return Fraction(numerator, 1001)
    return Fraction(str(value)).limit_denominator(100000)


def state_message(message):
    if message.get('type') not in ('state', 'ack'):
        raise ValueError('Expected timeline state')
    frame, start, end = (number(message[key]) for key in ('frame', 'start', 'end'))
    if start > end:
        raise ValueError('Invalid timeline range')
    return dict(frame=frame, start=start, end=end, fps=frame_rate(message['fps']))


def to_cadence(frame, origin, dcc_fps, timeline_fps, offset):
    return rounded((Fraction(str(frame)) - Fraction(str(origin))) * timeline_fps / dcc_fps) + offset


def to_host(frame, origin, dcc_fps, timeline_fps, offset):
    return float(Fraction(str(origin)) + Fraction(frame - offset) * dcc_fps / timeline_fps)


class TimelineLink(QObject):
    changed = Signal()

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.host = None
        self.direction = 'both'
        self.offset = 0
        self.from_start = True
        self.server = None
        self.peer = None
        self.lock = None
        self.token = None
        self.metadata = None
        self.pending = None
        self.last_position = None
        self.sequence = 0
        self.awaiting = None
        self.last_received = 0.
        self.last_ping = 0.
        self.next_rate_check = 0.
        self.rate_decisions = set()
        self.prompt_open = False
        self.dialog = None
        self.drawing_capability = False
        self.drawing_removal = False
        self.drawing_request = None
        self.drawing_bundle = None
        self.cameras = []
        self.transfer_status = ''
        self.status = 'Synchronisation désactivée'
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.tick)
        try:
            data = json.loads(preference_path().with_name('sync3d.json').read_text(encoding='utf-8'))
            if data.get('direction') in ('both', 'receive', 'send'): self.direction = data['direction']
            if type(data.get('offset')) is int: self.offset = max(-10000000, min(10000000, data['offset']))
            self.from_start = data.get('from_start', True) is True
        except (OSError, ValueError, TypeError):
            pass

    @property
    def enabled(self):
        return self.server is not None

    def save(self):
        write_file(preference_path().with_name('sync3d.json'), dict(
            direction=self.direction, offset=self.offset, from_start=self.from_start))

    def choose_host(self):
        from sync3d_dialog import choose_host
        return choose_host(self.window)

    def prepare_connector(self):
        from sync3d_setup import install_connector
        return install_connector(self.host)

    def set_enabled(self, enabled):
        if not enabled:
            self.stop()
            return
        if self.enabled:
            return
        if self.host is None:
            self.host = self.choose_host()
            if self.host is None:
                self.changed.emit()
                return
        path = endpoint_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            lock = QLockFile(str(path.with_suffix('.lock')))
            if not lock.tryLock(0):
                raise OSError(tr('Une autre fenêtre Cadence utilise déjà la synchronisation 3D.'))
            self.lock = lock
            installed = self.prepare_connector()
            server = QTcpServer(self)
            if not server.listen(QHostAddress.SpecialAddress.LocalHost, 0):
                server.deleteLater()
                raise OSError(server.errorString())
            self.server = server
            self.token = secrets.token_hex(32)
            write_file(path, dict(version=1, port=server.serverPort(), token=self.token, host=self.host, pid=os.getpid()))
            server.newConnection.connect(self.accept)
            self.status = ('Connecteur installé. Démarrez ou redémarrez le logiciel 3D pour la première connexion.'
                if installed else 'En attente du logiciel 3D')
            self.changed.emit()
            if installed:
                from PySide6.QtWidgets import QMessageBox
                application = 'Blender' if self.host == 'blender' else 'Maya'
                QMessageBox.information(self.window, tr('Première synchronisation'),
                    tr('Le connecteur est installé. Redémarrez {application} pour activer la synchronisation.\nEnsuite, la case suffira pour connecter ou déconnecter Cadence.').format(application=application))
            logging.info('3D synchronization enabled: %s, port=%s', self.host, server.serverPort())
        except OSError as error:
            self.stop()
            self.window.error(str(error))

    def stop(self):
        self.timer.stop()
        if self.peer:
            self.send(dict(type='stop'))
            self.peer.flush()
            self.peer.disconnectFromHost()
        self.peer = None
        if self.server:
            self.server.close()
            self.server.deleteLater()
            self.server = None
        if self.token:
            try:
                path = endpoint_path()
                if json.loads(path.read_text(encoding='utf-8')).get('token') == self.token:
                    path.unlink(missing_ok=True)
            except (OSError, ValueError):
                logging.warning('Could not remove 3D synchronization endpoint', exc_info=True)
        self.token = None
        if self.lock:
            self.lock.unlock()
            self.lock = None
        self.metadata = self.pending = None
        self.awaiting = None
        self.drawing_capability = False
        self.drawing_removal = False
        self.drawing_request = None
        self.cameras = []
        self.status = 'Synchronisation désactivée'
        self.changed.emit()

    def accept(self):
        while self.server and self.server.hasPendingConnections():
            peer = self.server.nextPendingConnection()
            if self.peer:
                peer.abort(); peer.deleteLater(); continue
            self.peer = peer
            peer.setReadBufferSize(16385)
            peer.setSocketOption(QAbstractSocket.SocketOption.LowDelayOption, 1)
            peer.authenticated = False
            peer.buffer = b''
            peer.readyRead.connect(lambda p=peer: self.read(p))
            peer.disconnected.connect(lambda p=peer: self.disconnected(p))
            self.last_received = time.monotonic()
            self.timer.start()

    def disconnected(self, peer):
        if peer is self.peer:
            self.peer = None
            self.metadata = self.pending = None
            self.awaiting = None
            self.drawing_capability = False
            self.drawing_removal = False
            self.drawing_request = None
            self.cameras = []
            self.timer.stop()
            self.status = 'En attente du logiciel 3D' if self.enabled else 'Synchronisation désactivée'
            self.changed.emit()
        peer.deleteLater()

    def read(self, peer):
        if peer is not self.peer:
            return
        try:
            peer.buffer += bytes(peer.readAll())
            if len(peer.buffer) > 16384:
                raise ValueError('Timeline message too large')
            while b'\n' in peer.buffer:
                line, peer.buffer = peer.buffer.split(b'\n', 1)
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError('Invalid timeline message')
                if not peer.authenticated:
                    if (message.get('type') != 'hello' or message.get('version') != 1 or
                        message.get('host') != self.host or not isinstance(message.get('token'), str) or
                        not secrets.compare_digest(message['token'], self.token)):
                        raise ValueError('Invalid timeline handshake')
                    peer.authenticated = True
                    self.send(dict(type='ready'))
                    self.status = 'Connecté'
                    self.last_position = None
                    self.changed.emit()
                else:
                    if message.get('type') in ('capabilities','drawing_cameras','drawing_result'):
                        self.read_drawing(message)
                        self.last_received = time.monotonic()
                        continue
                    state = state_message(message)
                    previous = self.metadata
                    acknowledgement = message.get('type') == 'ack'
                    if acknowledgement:
                        if type(message.get('seq')) is not int or message['seq'] != self.awaiting:
                            raise ValueError('Unexpected frame acknowledgement')
                        self.awaiting = None
                    if not acknowledgement and self.awaiting is None and state != self.metadata:
                        self.pending = state
                    self.metadata = state
                    if previous is None or any(previous[k] != state[k] for k in ('fps', 'start', 'end')):
                        self.changed.emit()
                self.last_received = time.monotonic()
        except (ValueError, KeyError, TypeError, OverflowError):
            logging.warning('Rejected invalid 3D synchronization message', exc_info=True)
            peer.abort()

    def send(self, message):
        if not self.peer or not self.peer.authenticated or self.peer.bytesToWrite() > 4096:
            return False
        self.peer.write((json.dumps(message, allow_nan=False) + '\n').encode())
        return True

    def origin(self):
        return self.metadata['start'] if self.from_start else 0

    def tick(self):
        now = time.monotonic()
        if now - self.last_received > (180 if self.drawing_request else 5):
            if self.peer: self.peer.abort()
            return
        if now - self.last_ping > 1:
            self.send(dict(type='ping'))
            self.last_ping = now
        w = self.window
        if not self.metadata or w.job or self.prompt_open or self.drawing_request or not w.doc.state.length:
            return
        if self.pending and self.direction != 'send':
            state, self.pending = self.pending, None
            target = to_cadence(state['frame'], self.origin(), state['fps'], w.doc.fps, self.offset)
            target = max(0, min(w.doc.state.length - 1, target))
            if target != w.doc.state.position:
                w.seek(target)
            self.last_position = w.doc.state.position
        else:
            self.pending = None
        if self.direction != 'receive' and self.awaiting is None and w.doc.state.position != self.last_position:
            target = to_host(w.doc.state.position, self.origin(), self.metadata['fps'], w.doc.fps, self.offset)
            self.sequence = (self.sequence + 1) % 2147483648
            if self.send(dict(type='frame', frame=target, seq=self.sequence)):
                self.awaiting = self.sequence
                self.last_position = w.doc.state.position
        if now >= self.next_rate_check:
            self.next_rate_check = now + 1.
            self.check_rate()

    def read_drawing(self,message):
        kind=message['type']
        if kind=='capabilities':
            self.drawing_capability=message.get('drawings')==1
            self.drawing_removal=message.get('drawing_remove')==1
            if self.drawing_capability: self.refresh_cameras()
        elif kind=='drawing_cameras':
            cameras=message.get('cameras')
            if not isinstance(cameras,list) or len(cameras)>64 or any(not isinstance(c,str) or len(c)>1024 for c in cameras):
                raise ValueError('Invalid camera list')
            self.cameras=cameras
        elif kind=='drawing_result':
            if self.drawing_request and message.get('request')!=self.drawing_request:
                raise ValueError('Unexpected drawing acknowledgement')
            self.drawing_request=None
            if self.drawing_bundle:
                import shutil
                from pathlib import Path
                folder=Path(self.drawing_bundle).resolve().parent
                if folder.is_relative_to((endpoint_path().parent/'drawing_transfers').resolve()):
                    try: shutil.rmtree(folder)
                    except OSError: logging.warning('Could not remove drawing transfer staging folder',exc_info=True)
                self.drawing_bundle=None
            if message.get('ok'):
                text=('Dessins envoyés supprimés.' if message.get('removed') else
                    'Dessins envoyés dans Blue Pencil : {keys} clés.' if message.get('blue_pencil') else
                    'Dessins envoyés : {keys} clés, {native} en traits, {images} en images.')
                self.transfer_status=tr(text).format(**message)
                if message.get('collapsed'):
                    self.transfer_status+=' '+tr('{count} clés trop courtes pour la cadence 3D.').format(count=message['collapsed'])
            else:
                self.transfer_status=tr('Échec du transfert des dessins.')
                error=str(message.get('error',''))
                logging.error('3D drawing transfer failed: %s',error)
                hints={
                    'Selected camera no longer exists':'La caméra a été supprimée. Actualisez la liste des caméras.',
                    'Selected object is not a camera':'Choisissez une caméra dans le logiciel 3D.',
                    'Camera clipping range is too small':'Augmentez la distance entre les plans de coupe de la caméra.',
                    'Wait for the current render to finish':'Attendez la fin du rendu en cours.',
                    'Grease Pencil transfer requires Blender 4.3 or later; choose transparent images':'Grease Pencil nécessite Blender 4.3 ou ultérieur. Choisissez le mode images.',
                    'Blue Pencil requires the Maya interface; batch mode is not supported':'Ouvrez Maya avec son interface pour utiliser Blue Pencil.',
                    'Blue Pencil requires a unique camera name':'Donnez un nom unique à la caméra dans Maya.',
                    'Refresh the camera list before sending Blue Pencil drawings':'Actualisez la liste des caméras avant l’envoi.',
                }
                self.window.error(self.transfer_status+'\n'+tr(hints.get(error,'Le détail de l’erreur est disponible dans Aide > Dossier des journaux.')))
        self.changed.emit()

    def remove_drawings(self):
        import uuid
        from PySide6.QtWidgets import QMessageBox
        if not self.metadata or not self.drawing_removal or self.drawing_request or self.window.job: return
        token=self.token
        answer=QMessageBox.question(self.window,tr('Supprimer les dessins'),
            tr('Supprimer tous les dessins créés par Cadence ?'),
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
        if answer!=QMessageBox.StandardButton.Yes or token!=self.token: return
        request=uuid.uuid4().hex
        if self.send(dict(type='drawing_remove',scope='all_cadence',request=request)):
            self.drawing_request=request
            self.transfer_status=tr('Suppression des dessins envoyés…')
            self.changed.emit()

    def refresh_cameras(self):
        if self.drawing_capability and not self.drawing_request: self.send(dict(type='drawing_cameras'))

    def send_drawings(self,camera,mode,onion):
        import uuid
        from drawing_transfer import build_bundle
        w=self.window
        if not self.metadata or not self.drawing_capability or self.drawing_request or w.job:
            return
        if camera not in self.cameras:
            w.error(tr('Choisissez une caméra dans le logiciel 3D.')); return
        if self.host=='maya' and mode not in ('images','blue_pencil'): mode='blue_pencil'
        w.drawing.finish()
        doc=w.doc
        media=next((m for m in doc.media.values() if m.get('has_video',True)),{'width':1920,'height':1080})
        width,height=media['width'],media['height']
        scale=min(1.,4096/max(width,height)); width=max(2,round(width*scale)); height=max(2,round(height*scale))
        onion=bool(onion and w.drawing.onion.isChecked())
        before=w.drawing.before.value() if onion else 0
        after=w.drawing.after.value() if onion else 0
        opacity=w.drawing.ghost.value()/100.
        keys=doc.state.drawings; fps=doc.fps; host_fps=self.metadata['fps']; origin=self.origin(); offset=self.offset
        token=self.token; request=uuid.uuid4().hex
        self.transfer_status=tr('Préparation des dessins'); self.changed.emit()
        def prepared(path):
            if token!=self.token or not self.peer:
                self.transfer_status=tr('Connexion interrompue. Renvoyez les dessins.'); self.changed.emit(); return
            if self.send(dict(type='drawing_send',path=path,request=request)):
                self.drawing_request=request
                self.drawing_bundle=path
                self.transfer_status=tr('Importation dans le logiciel 3D…')
            else: self.transfer_status=tr('Connexion interrompue. Renvoyez les dessins.')
            self.changed.emit()
        w.begin_task(tr('Préparation des dessins'),lambda progress,cancel:build_bundle(
            keys,endpoint_path().parent/'drawing_transfers',doc.drawing_transfer_id,width,height,fps,host_fps,
            origin,offset,camera,mode,before,after,opacity,progress,cancel),prepared)
        if w.job:
            w.job.finished.connect(lambda:QTimer.singleShot(0,self.changed.emit))

    def send_current_drawings(self):
        if self.dialog is None:
            self.show_dialog()
            return
        d=self.dialog
        self.send_drawings(d.camera.currentData(),d.drawing_mode.currentData(),d.onion.isChecked())

    def configure(self, host, direction, offset, from_start):
        if host not in (None, 'blender', 'maya') or direction not in ('both', 'receive', 'send'):
            raise ValueError('Invalid synchronization settings')
        restart = host != self.host and self.enabled
        if restart: self.stop()
        self.host, self.direction, self.offset, self.from_start = host, direction, offset, from_start
        self.last_position = None
        self.pending = self.metadata if direction != 'send' else None
        self.save()
        if restart and host is not None: self.set_enabled(True)
        self.changed.emit()

    def check_rate(self):
        from model import locate
        w = self.window
        key, _ = locate(w.doc.state.segments, min(w.doc.state.position, w.doc.state.length - 1))
        media = w.doc.media.get(key)
        if not media or not media.get('has_video', True):
            return
        target = self.metadata['fps']
        current = Fraction(media.get('cadence', {}).get('rate', media.get('original_fps', media['fps'])))
        identity = (id(w.doc), key, str(target))
        if abs(float(current - target)) < .001 or identity in self.rate_decisions:
            return
        self.rate_decisions.add(identity)
        self.prompt_open = True
        QTimer.singleShot(0, lambda: self.offer_rate(w.doc, key, current, target))

    def offer_rate(self, document, key, current, target):
        from PySide6.QtWidgets import QMessageBox
        try:
            w = self.window
            if not self.enabled or w.doc is not document or w.job:
                self.rate_decisions.discard((id(document), key, str(target)))
                return
            message = tr('Cadence du média : {media} images/s. Cadence 3D : {host} images/s.\nAdapter ce média en conservant sa durée ?\nLa cadence de la timeline reste inchangée.').format(media=f'{float(current):g}', host=f'{float(target):g}')
            answer = QMessageBox.question(w, tr('Synchronisation 3D'), message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                self.adapt_media(document, key, target)
        finally:
            self.prompt_open = False

    def adapt_media(self, document, key, target):
        return self.adapt_keys(document, {key}, target)

    def adapt_current(self, all_media=False):
        from model import locate
        from PySide6.QtWidgets import QMessageBox
        w = self.window
        if not self.metadata or w.job or not w.doc.state.length:
            return
        keys = ({s.media for s in w.doc.state.segments} if all_media else
            {locate(w.doc.state.segments, min(w.doc.state.position, w.doc.state.length - 1))[0]})
        keys = {key for key in keys if key in w.doc.media and w.doc.media[key].get('has_video', True)}
        if not keys:
            return
        target = self.metadata['fps']
        self.prompt_open = True
        try:
            message = tr('Adapter {count} média(s) à {rate} images/s ?\nLeur durée et la cadence de la timeline restent inchangées.').format(count=len(keys), rate=f'{float(target):g}')
            if QMessageBox.question(w, tr('Synchronisation 3D'), message,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes) == QMessageBox.StandardButton.Yes:
                self.adapt_keys(w.doc, keys, target)
        finally:
            self.prompt_open = False

    def adapt_keys(self, document, keys, target):
        from cadence_change import plan_ranges, build_change
        w = self.window
        if w.job or w.doc is not document:
            return
        w.pause(); w.drawing.finish(); w.commit_exposure()
        state = document.state
        ranges = plan_ranges(state, document.media, keys=keys)
        if not ranges:
            return
        def prepare(progress, cancel):
            return build_change(state, document.media, document.fps, ranges, target, 'duration', True,
                w.preferences.get('preview_quality', 'native'), progress, cancel)
        def apply(result):
            changed, media = result
            document.media = media
            document.commit('Changer la cadence', changed)
            w.library_signature = None; w.refresh(); w.request_frame()
            self.changed.emit()
        w.begin_task('Changement de cadence', prepare, apply)

    def show_dialog(self):
        from sync3d_dialog import SyncDialog
        if self.dialog is None:
            self.dialog = SyncDialog(self, self.window)
        self.dialog.show(); self.dialog.raise_(); self.dialog.activateWindow()


def install(window):
    link = TimelineLink(window)
    window.sync3d = link
    menu = window.menuBar().addMenu(tr('Synchronisation 3D'))
    help_action = next((a for a in window.menuBar().actions() if a.menu() and a.menu().title() == tr('Aide')), None)
    if help_action:
        window.menuBar().insertMenu(help_action, menu)
    toggle = window.action(menu, 'Activer la synchronisation', link.set_enabled, 'Ctrl+Alt+S')
    toggle.setCheckable(True)
    window.action(menu, 'Réglages de synchronisation…', link.show_dialog, 'Ctrl+Alt+L')
    menu.addSeparator()
    current = window.action(menu, 'Adapter la cadence du média courant…', link.adapt_current, 'Ctrl+Alt+R')
    all_media = window.action(menu, 'Adapter la cadence de tous les médias…', lambda:link.adapt_current(True), 'Ctrl+Alt+Shift+R')
    menu.addSeparator()
    drawings = window.action(menu, 'Envoyer les dessins', link.send_current_drawings, 'Ctrl+Alt+D')
    def update():
        toggle.setChecked(link.enabled)
        for action in (current, all_media): action.setEnabled(link.metadata is not None)
        drawings.setEnabled(bool(link.drawing_capability and link.metadata and not link.drawing_request))
    link.changed.connect(update)
    update()
