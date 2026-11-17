# SPDX-License-Identifier: GPL-3.0-only
import errno
import json
import logging
import math
import os
import select
import socket
import sys

if __package__:
    from .cadence_runtime import endpoint_path, finite, fs_path, integer_types, load_source, maya_timer, monotonic, read_json, string_types
else:
    from cadence_runtime import endpoint_path, finite, fs_path, integer_types, load_source, maya_timer, monotonic, read_json, string_types

bl_info = {'name': 'Cadence', 'author': 'Cadence', 'version': (1, 17, 0),
           'blender': (4, 0, 0), 'category': 'Animation',
    'description': 'Synchronize the timeline with Cadence'}


def number(value, limit=100000000):
    if isinstance(value, bool) or not isinstance(value, integer_types + (float,)):
        raise ValueError('Invalid timeline number')
    if not finite(value) or abs(value) > limit:
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
        self.drawing_job = None
        self.drawing_request = None
        self.drawing_progress = -1
        self.drawing_state = None

    def disconnect(self):
        self.cancel_drawing(notify=False)
        if self.sock:
            self.sock.close()
        self.sock = None
        self.authenticated = False
        self.incoming = self.outgoing = b''
        self.last_state = None
        self.next_connect = monotonic() + 1.

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
            info = read_json(endpoint_path())
            if not isinstance(info, dict) or info.get('version') != 1 or info.get('host') != self.host:
                return
            port = info['port']
            if type(port) is not int or not 1024 <= port <= 65535:
                return
            if not isinstance(info.get('token'), string_types) or len(info['token']) != 64:
                return
        except (IOError, OSError, ValueError, KeyError, TypeError):
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
        now = monotonic()
        try:
            if self.sock is None and now >= self.next_connect:
                self.connect(now)
            if self.sock is None:
                return 1.
            if now - self.received > (180 if self.drawing_job is not None else 5):
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
                        self.queue(dict(type='capabilities', drawings=1, drawing_remove=1, drawing_cancel=int(self.host=='maya'), drawing_modes=self.drawing_modes()))
                    elif message.get('type') == 'stop' and self.authenticated:
                        self.close()
                        return None
                    elif message.get('type') == 'frame' and self.authenticated:
                        sequence = message.get('seq')
                        if type(sequence) is not int or not 0 <= sequence <= 2147483647:
                            raise ValueError('Invalid frame sequence')
                        commands.append((number(message['frame']), sequence, self.drawing_job is None))
                    elif message.get('type')=='drawing_cancel' and self.authenticated:
                        if message.get('request')==self.drawing_request: self.cancel_drawing()
                    elif message.get('type') in ('drawing_cameras','drawing_send','drawing_remove') and self.authenticated:
                        self.drawing_command(message)
                        now=monotonic(); self.received=now
            # Only the latest requested time matters when the host is rendering slowly.
            if commands:
                if self.drawing_job is None and commands[-1][2]: self.set_frame(commands[-1][0])
                self.last_state = self.drawing_state if self.drawing_job is not None else self.snapshot()
                self.queue(dict(type='ack', seq=commands[-1][1], **self.last_state))
                self.last_sent = now
            self.advance_drawing()
            if self.authenticated and not self.outgoing:
                state = self.drawing_state if self.drawing_job is not None else self.snapshot()
                if state != self.last_state or now - self.last_sent >= 1:
                    self.queue(dict(type='state', **state))
                    self.last_state = state
                    self.last_sent = now
        except (IOError, OSError, ValueError, TypeError, KeyError, RuntimeError):
            logging.debug('Cadence timeline disconnected', exc_info=True)
            self.disconnect()
        return .008 if self.drawing_job is not None else .033 if self.sock else 1.

    def drawing_module(self):
        if self.drawings is None:
            path = os.path.join(os.path.dirname(fs_path(__file__)), 'cadence_drawings.py')
            self.drawings = load_source((__package__+'.' if __package__ else '')+'cadence_drawings', path)
        return self.drawings

    def drawing_modes(self):
        if self.host == 'blender':
            return ['native', 'images']
        return self.drawing_module().module('maya').modes()

    def drawing_command(self,message):
        if self.drawing_job is not None:
            self.queue(dict(type='drawing_result',request=message.get('request',''),ok=False,error='A drawing transfer is already running'))
            return
        if self.host=='maya' and message['type']=='drawing_send':
            self.drawing_state=self.snapshot()
            self.drawing_request=message['request']; self.drawing_progress=-1
            self.drawing_job=self.drawing_module().execute_steps(self.host,message,os.path.join(os.path.dirname(fs_path(endpoint_path())), 'drawing_transfers'))
            return
        try:
            result=self.drawing_module().execute(self.host,message,os.path.join(os.path.dirname(fs_path(endpoint_path())), 'drawing_transfers'))
        except Exception as error:
            logging.exception('Cadence drawing transfer failed')
            result=dict(type='drawing_result',request=message.get('request',''),ok=False,error=str(error)[:1000])
        self.queue(result)

    def cancel_drawing(self,notify=True):
        job,self.drawing_job=self.drawing_job,None
        request,self.drawing_request=self.drawing_request,None
        if job is None: return
        try: job.close()
        except Exception: logging.exception('Could not roll back Cadence drawing transfer')
        self.last_state=None
        self.received=monotonic()
        if notify: self.queue(dict(type='drawing_result',request=request,ok=False,cancelled=True))

    def advance_drawing(self):
        if self.drawing_job is None: return
        deadline=monotonic()+.02
        try:
            for step in range(32):
                update=next(self.drawing_job)
                if 'result' in update:
                    self.drawing_job.close(); self.drawing_job=None; self.drawing_request=None
                    self.received=monotonic()
                    self.last_state=None; self.queue(update['result']); return
                progress=int(update.get('progress',0))
                if progress!=self.drawing_progress:
                    self.drawing_progress=progress
                    self.queue(dict(type='drawing_progress',request=self.drawing_request,progress=progress))
                if monotonic()>=deadline: break
        except Exception as error:
            request=self.drawing_request
            self.cancel_drawing(notify=False)
            cancelled=bool(getattr(error,'cancelled',False))
            if not cancelled: logging.exception('Cadence drawing transfer failed')
            self.queue(dict(type='drawing_result',request=request,ok=False,cancelled=cancelled,error=str(error)[:1000]))


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
        timer = maya_timer()
        timer.setSingleShot(True)
        def poll():
            delay = bridge.tick()
            if delay is not None:
                timer.start(max(1, int(round(delay * 1000))))
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
