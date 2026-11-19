# SPDX-License-Identifier: GPL-3.0-only
import json
import logging
import secrets
import time

from PySide6.QtNetwork import QAbstractSocket


class InstanceConnections:
    def accept(self):
        while self.server and self.server.hasPendingConnections():
            peer = self.server.nextPendingConnection()
            if len(self.peers) >= 16:
                peer.abort(); peer.deleteLater(); continue
            self.peer_serial += 1
            peer.identity = 'connection-' + str(self.peer_serial)
            peer.instance_label = self.host.title() + ' · ' + str(self.peer_serial)
            peer.metadata = None; peer.capabilities = None; peer.cameras = []
            peer.awaiting = None; peer.last_ping = 0.; peer.last_received = time.monotonic()
            peer.authenticated = False; peer.stable_identity = False; peer.buffer = b''
            self.peers.append(peer)
            if self.peer is None and self.selected_instance is None:
                self.peer = peer
                self.last_received = peer.last_received
            peer.setReadBufferSize(16385)
            peer.setSocketOption(QAbstractSocket.SocketOption.LowDelayOption, 1)
            peer.readyRead.connect(lambda p=peer: self.read(p))
            peer.disconnected.connect(lambda p=peer: self.disconnected(p))
            self.timer.start()

    def instances(self):
        return [(p.identity, p.instance_label) for p in self.peers if p.authenticated]

    def reset_peer_state(self):
        self.cancel_pending_rate()
        self.close_import_dialog()
        self.metadata = self.pending = self.awaiting = self.last_position = None
        self.drawing_capability = self.drawing_removal = self.drawing_cancellation = False
        self.drawing_modes = self.drawing_request = None
        self.cameras = []; self.transfer_status = ''

    def select_instance(self, identity):
        if self.drawing_request: return False
        peer = next((p for p in self.peers if p.identity == identity and p.authenticated), None)
        if peer is None: return False
        self.reset_peer_state()
        self.peer = peer; self.selected_instance = peer.identity
        self.metadata = peer.metadata; self.pending = peer.metadata
        self.awaiting = peer.awaiting; self.last_received = peer.last_received
        self.status = 'Connecté'
        self.rate_decisions.clear(); self.next_rate_check = 0.
        if peer.capabilities: self.read_drawing(peer.capabilities)
        self.changed.emit()
        return True

    def disconnected(self, peer):
        if peer not in self.peers: return
        self.peers.remove(peer)
        if peer is self.peer:
            if not peer.stable_identity: self.selected_instance = None
            self.reset_peer_state(); self.peer = None
            self.status = ('Instance sélectionnée déconnectée' if self.selected_instance else
                           'En attente du logiciel 3D') if self.enabled else 'Synchronisation désactivée'
        if not self.peers: self.timer.stop()
        self.changed.emit(); peer.deleteLater()

    def stop_peers(self):
        peers, self.peers = self.peers, []
        self.peer = None; self.selected_instance = None
        for peer in peers:
            self.send_peer(peer, dict(type='stop')); peer.flush()
            peer.disconnectFromHost(); peer.deleteLater()

    def update_instance_label(self, peer, message):
        info = message.get('instance')
        if info is None: return
        if not isinstance(info, dict): raise ValueError('Invalid host instance')
        application, scene, pid = info.get('application', self.host.title()), info.get('scene', ''), info.get('pid')
        if any(not isinstance(value, str) or len(value) > 1024 for value in (application, scene)):
            raise ValueError('Invalid instance label')
        if type(pid) is not int or not 0 < pid < 2147483648: raise ValueError('Invalid host process')
        label = ' · '.join(part.replace('\n', ' ').replace('\r', ' ') for part in
                           (application, scene, 'PID ' + str(pid)) if part)
        if peer.instance_label != label:
            peer.instance_label = label; self.changed.emit()

    def read(self, peer):
        from sync3d import state_message
        if peer not in self.peers: return
        try:
            peer.buffer += bytes(peer.readAll())
            if len(peer.buffer) > 16384: raise ValueError('Timeline message too large')
            while b'\n' in peer.buffer:
                line, peer.buffer = peer.buffer.split(b'\n', 1)
                message = json.loads(line)
                if not isinstance(message, dict): raise ValueError('Invalid timeline message')
                peer.last_received = time.monotonic()
                if peer is self.peer: self.last_received = peer.last_received
                if not peer.authenticated:
                    if (message.get('type') != 'hello' or message.get('version') != 1 or
                            message.get('host') != self.host or not isinstance(message.get('token'), str) or
                            not secrets.compare_digest(message['token'], self.token)):
                        raise ValueError('Invalid timeline handshake')
                    identity = message.get('instance_id', peer.identity)
                    if not isinstance(identity, str) or not 1 <= len(identity) <= 128:
                        raise ValueError('Invalid host identity')
                    if any(p is not peer and p.authenticated and p.identity == identity for p in self.peers):
                        raise ValueError('Duplicate host identity')
                    peer.identity = identity; peer.stable_identity = 'instance_id' in message; peer.authenticated = True
                    self.send_peer(peer, dict(type='ready'))
                    if self.selected_instance in (None, identity): self.select_instance(identity)
                    self.changed.emit()
                    continue
                self.update_instance_label(peer, message)
                kind = message.get('type')
                if kind in ('capabilities', 'drawing_cameras', 'drawing_result', 'drawing_progress'):
                    if kind == 'capabilities':
                        modes = message.get('drawing_modes')
                        if modes is not None and (not isinstance(modes, list) or not 1 <= len(modes) <= 4 or
                                any(mode not in ('native', 'images', 'blue_pencil', 'grease_pencil') for mode in modes)):
                            raise ValueError('Invalid drawing modes')
                        peer.capabilities = message
                    elif kind == 'drawing_cameras':
                        cameras = message.get('cameras')
                        if not isinstance(cameras, list) or len(cameras) > 64 or any(not isinstance(c, str) or len(c) > 1024 for c in cameras):
                            raise ValueError('Invalid camera list')
                        peer.cameras = cameras
                    if peer is self.peer: self.read_drawing(message)
                    elif kind not in ('capabilities', 'drawing_cameras'):
                        raise ValueError('Unexpected inactive drawing response')
                    continue
                state = state_message(message)
                acknowledgement = kind == 'ack'
                if acknowledgement:
                    if type(message.get('seq')) is not int or message['seq'] != peer.awaiting:
                        raise ValueError('Unexpected frame acknowledgement')
                    peer.awaiting = None
                peer.metadata = state
                if peer is self.peer:
                    previous = self.metadata
                    if acknowledgement: self.awaiting = None
                    if not acknowledgement and self.awaiting is None and state != self.metadata:
                        self.pending = state
                    self.metadata = state
                    if previous is None or any(previous[k] != state[k] for k in ('fps', 'start', 'end')):
                        self.changed.emit()
        except (ValueError, KeyError, TypeError, OverflowError):
            logging.warning('Rejected invalid 3D synchronization message', exc_info=True)
            peer.abort()

    def send_peer(self, peer, message):
        if not peer or not peer.authenticated or peer.bytesToWrite() > 4096: return False
        peer.write((json.dumps(message, allow_nan=False) + '\n').encode())
        if message.get('type') == 'frame': peer.awaiting = message['seq']
        return True

    def send(self, message):
        return self.send_peer(self.peer, message)

    def maintain_peers(self, now):
        for peer in tuple(self.peers):
            last = self.last_received if peer is self.peer else peer.last_received
            limit = 180 if peer is self.peer and self.drawing_request else 5
            if now - last > limit:
                peer.abort(); continue
            if now - peer.last_ping > 1:
                self.send_peer(peer, dict(type='ping')); peer.last_ping = now
