# SPDX-License-Identifier: GPL-3.0-only
import ctypes
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys


def endpoint_path():
    return Path(os.environ.get('CADENCE_SYNC_ENDPOINT') or
        (Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'CadenceStudio' / 'sync_endpoint.json'))


def owner_alive(pid):
    if type(pid) is not int or pid <= 0:
        return False
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        kernel.CloseHandle(handle)


class Monitor:
    def __init__(self, host):
        self.host = host
        self.module = None
        self.token = None
        self.timer = None
        self.active = True

    def stop_bridge(self):
        if self.module:
            self.module.stop()
        self.module = None
        self.token = None

    def tick(self):
        if not self.active:
            return None
        try:
            info = json.loads(endpoint_path().read_text(encoding='utf-8'))
            valid = (isinstance(info, dict) and info.get('version') == 1 and info.get('host') == self.host and
                isinstance(info.get('token'), str) and len(info['token']) == 64 and owner_alive(info.get('pid')))
        except (OSError, ValueError, TypeError):
            valid = False
        if not valid:
            self.stop_bridge()
            return 1.
        if info['token'] != self.token:
            self.stop_bridge()
            try:
                previous = sys.modules.get('cadence_bridge')
                if previous: previous.stop()
                spec = importlib.util.spec_from_file_location('cadence_bridge', Path(__file__).with_name('cadence_bridge.py'))
                module = importlib.util.module_from_spec(spec)
                sys.modules['cadence_bridge'] = module
                spec.loader.exec_module(module)
                module.start(self.host)
                self.module, self.token = module, info['token']
            except Exception:
                logging.exception('Cadence connector could not start')
                self.stop_bridge()
        return 1.


_monitor = None


def shutdown():
    global _monitor
    monitor, _monitor = _monitor, None
    if monitor is None:
        return
    monitor.active = False
    monitor.stop_bridge()
    if monitor.host == 'blender':
        import bpy
        if bpy.app.timers.is_registered(monitor.tick):
            bpy.app.timers.unregister(monitor.tick)
    elif monitor.timer:
        monitor.timer.stop()
        monitor.timer.deleteLater()


def start(host):
    global _monitor
    if _monitor and _monitor.host == host:
        return
    shutdown()
    monitor = _monitor = Monitor(host)
    if host == 'blender':
        import bpy
        bpy.app.timers.register(monitor.tick, first_interval=0., persistent=True)
    elif host == 'maya':
        try:
            from PySide6.QtCore import QTimer
        except ImportError:
            from PySide2.QtCore import QTimer
        monitor.timer = QTimer()
        monitor.timer.setInterval(1000)
        monitor.timer.timeout.connect(monitor.tick)
        monitor.timer.start()
        monitor.tick()
