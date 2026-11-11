# SPDX-License-Identifier: GPL-3.0-only
import errno
import json
import logging
import math
import os
from pathlib import Path
import select
import socket
import time

bl_info = {'name': 'Cadence', 'author': 'Cadence', 'version': (1, 15, 1),
           'blender': (4, 0, 0), 'category': 'Animation',
    'description': 'Synchronize the timeline with Cadence'}


def endpoint_path():
    override = os.environ.get('CADENCE_SYNC_ENDPOINT')
    if override:
        return Path(override)
    return Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'CadenceStudio' / 'sync_endpoint.json'


def number(value, limit=100000000):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('Invalid timeline number')
    if not math.isfinite(value) or abs(value) > limit:
        raise ValueError('Timeline number outside supported range')
    return value


class Bridge:
    def __init__(self, host, snapshot, set_frame):
        self.host = host
        self.snapshot = snapshot
        self.set_frame = set_frame
        self.sock = None
        self.connecting = False
        self.authenticated = False
        self.incoming = b''
        self.outgoing = b''
        self.last_state = None
        self.next_connect = 0.
        self.last_sent = 0.
        self.received = 0.
        self.active = True
        self.poll_timer = None
        self.drawings = None

    def disconnect(self):
        if self.sock:
            self.sock.close()
        self.sock = None
        self.authenticated = False
        self.incoming = self.outgoing = b''
        self.last_state = None
        self.next_connect = time.monotonic() + 1.

    def close(self):
        self.active = False
        if self.poll_timer:
            self.poll_timer.stop()
            self.poll_timer.deleteLater()
            self.poll_timer = None
        self.disconnect()

    def queue(self, message):
        payload = (json.dumps(message, allow_nan=False, separators=(',', ':')) + '\n').encode()
        if len(self.outgoing) + len(payload) > 16384:
            raise ValueError('Timeline connection is not responding')
        self.outgoing += payload

    def connect(self, now):
        self.next_connect = now + 1.
        try:
            info = json.loads(endpoint_path().read_text(encoding='utf-8'))
            if not isinstance(info, dict) or info.get('version') != 1 or info.get('host') != self.host:
                return
            port = info['port']
            if type(port) is not int or not 1024 <= port <= 65535:
                return
            if not isinstance(info.get('token'), str) or len(info['token']) != 64:
                return
        except (OSError, ValueError, KeyError, TypeError):
            return
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setblocking(False)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        result = self.sock.connect_ex(('127.0.0.1', port))
        if result not in (0, errno.EINPROGRESS, errno.EWOULDBLOCK, 10035):
            self.disconnect()
            return
        self.connecting = True
        self.received = now
        self.queue({'type': 'hello', 'version': 1, 'host': self.host, 'token': info['token']})

    def tick(self):
        if not self.active:
            return None
        now = time.monotonic()
        try:
            if self.sock is None and now >= self.next_connect:
                self.connect(now)
            if self.sock is None:
                return 1.
            if now - self.received > 5:
                self.disconnect()
                return 1.
            readable, writable, errors = select.select([self.sock], [self.sock] if self.outgoing or self.connecting else [], [self.sock], 0)
            if errors:
                raise OSError('Timeline socket failed')
            if self.connecting and writable:
                if self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR):
                    raise OSError('Timeline connection refused')
                self.connecting = False
            if writable and self.outgoing and not self.connecting:
                count = self.sock.send(self.outgoing)
                self.outgoing = self.outgoing[count:]
            commands = []
            if readable:
                data = self.sock.recv(16384)
                if not data:
                    raise OSError('Timeline connection closed')
                self.incoming += data
                if len(self.incoming) > 16384:
                    raise ValueError('Timeline message too large')
                while b'\n' in self.incoming:
                    line, self.incoming = self.incoming.split(b'\n', 1)
                    message = json.loads(line)
                    if not isinstance(message, dict):
                        raise ValueError('Invalid timeline message')
                    self.received = now
                    if message.get('type') == 'ready':
                        self.authenticated = True
                        self.queue(dict(type='capabilities',drawings=1,drawing_remove=1))
                    elif message.get('type') == 'stop' and self.authenticated:
                        self.close()
                        return None
                    elif message.get('type') == 'frame' and self.authenticated:
                        sequence = message.get('seq')
                        if type(sequence) is not int or not 0 <= sequence <= 2147483647:
                            raise ValueError('Invalid frame sequence')
                        commands.append((number(message['frame']), sequence))
                    elif message.get('type') in ('drawing_cameras','drawing_send','drawing_remove') and self.authenticated:
                        self.drawing_command(message)
                        now=time.monotonic(); self.received=now
            # Only the latest requested time matters when the host is rendering slowly.
            if commands:
                self.set_frame(commands[-1][0])
                self.last_state = self.snapshot()
                self.queue(dict(type='ack', seq=commands[-1][1], **self.last_state))
                self.last_sent = now
            if self.authenticated and not self.outgoing:
                state = self.snapshot()
                if state != self.last_state or now - self.last_sent >= 1:
                    self.queue(dict(type='state', **state))
                    self.last_state = state
                    self.last_sent = now
        except (OSError, ValueError, TypeError, KeyError, RuntimeError):
            logging.debug('Cadence timeline disconnected', exc_info=True)
            self.disconnect()
        return .033 if self.sock else 1.

    def drawing_command(self,message):
        try:
            if self.drawings is None:
                import importlib.util
                spec=importlib.util.spec_from_file_location('cadence_drawings',Path(__file__).with_name('cadence_drawings.py'))
                self.drawings=importlib.util.module_from_spec(spec); spec.loader.exec_module(self.drawings)
            result=self.drawings.execute(self.host,message,endpoint_path().parent/'drawing_transfers')
        except Exception as error:
            logging.exception('Cadence drawing transfer failed')
            result=dict(type='drawing_result',request=message.get('request',''),ok=False,error=str(error)[:1000])
        self.queue(result)


_bridge = None


def stop():
    global _bridge
    bridge, _bridge = _bridge, None
    if bridge:
        bridge.close()
        if bridge.host == 'blender':
            import bpy
            if bpy.app.timers.is_registered(bridge.tick):
                bpy.app.timers.unregister(bridge.tick)


def start(host=None):
    global _bridge
    stop()
    if host is None:
        try:
            import bpy
            host = 'blender'
        except ImportError:
            host = 'maya'
    if host == 'blender':
        import bpy

        def snapshot():
            scene = bpy.context.scene
            return {'frame': scene.frame_current + scene.frame_subframe,
                    'fps': scene.render.fps / scene.render.fps_base,
                    'start': scene.frame_start, 'end': scene.frame_end}

        def set_frame(frame):
            # Timers run on the UI thread; never mutate a scene from a render callback.
            if bpy.app.is_job_running('RENDER'):
                return
            scene = bpy.context.scene
            frame = max(-1048574., min(1048574., frame))
            scene.frame_set(math.floor(frame), subframe=frame - math.floor(frame))

        _bridge = Bridge(host, snapshot, set_frame)
        bpy.app.timers.register(_bridge.tick, first_interval=0., persistent=True)
    elif host == 'maya':
        import maya.cmds as cmds
        import maya.api.OpenMaya as om
        try:
            from PySide6.QtCore import QTimer
        except ImportError:
            from PySide2.QtCore import QTimer

        def snapshot():
            seconds = om.MTime(1., om.MTime.uiUnit()).asUnits(om.MTime.kSeconds)
            return {'frame': cmds.currentTime(query=True), 'fps': 1. / seconds,
                    'start': cmds.playbackOptions(query=True, minTime=True),
                    'end': cmds.playbackOptions(query=True, maxTime=True)}

        def set_frame(frame):
            if cmds.play(query=True, state=True):
                cmds.play(state=False)
            cmds.currentTime(frame, edit=True)

        _bridge = Bridge(host, snapshot, set_frame)
        bridge = _bridge
        timer = QTimer()
        timer.setSingleShot(True)
        def poll():
            delay = bridge.tick()
            if delay is not None:
                timer.start(max(1, round(delay * 1000)))
        timer.timeout.connect(poll)
        bridge.poll_timer = timer
        timer.start(0)
    else:
        raise ValueError('Unsupported 3D application')
    return _bridge


def register():
    start('blender')


def unregister():
    stop()
