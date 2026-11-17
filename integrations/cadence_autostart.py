# SPDX-License-Identifier: GPL-3.0-only
import ctypes
import logging
import os
import sys

if __package__:
    from .cadence_runtime import endpoint_path, fs_path, integer_types, load_source, maya_timer, read_json, string_types
else:
    from cadence_runtime import endpoint_path, fs_path, integer_types, load_source, maya_timer, read_json, string_types

logger = logging.getLogger('cadence.connector')


def report_failure(message):
    try:
        logger.exception(message)
    except Exception:
        pass


def owner_alive(pid):
    if isinstance(pid, bool) or not isinstance(pid, integer_types) or pid <= 0:
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
        module, self.module = self.module, None
        self.token = None
        if module:
            try:
                module.stop()
            except Exception:
                report_failure('Cadence connector could not stop')

    def tick(self):
        if not self.active:
            return None
        try:
            info = read_json(endpoint_path())
            valid = (isinstance(info, dict) and info.get('version') == 1 and info.get('host') == self.host and
                isinstance(info.get('token'), string_types) and len(info['token']) == 64 and owner_alive(info.get('pid')))
        except (IOError, OSError, ValueError, TypeError):
            valid = False
        if not valid:
            self.stop_bridge()
            return 1.
        if info['token'] != self.token:
            self.stop_bridge()
            try:
                previous = sys.modules.get('cadence_bridge')
                if previous: previous.stop()
                module = load_source('cadence_bridge', os.path.join(os.path.dirname(fs_path(__file__)), 'cadence_bridge.py'))
                self.module = module
                module.start(self.host)
                self.token = info['token']
            except Exception:
                report_failure('Cadence connector could not start')
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
        monitor.timer = maya_timer()
        monitor.timer.setInterval(1000)
        monitor.timer.timeout.connect(monitor.tick)
        monitor.timer.start()
        monitor.tick()


def safe_start(host):
    try:
        start(host)
    except (Exception, SystemExit):
        report_failure('Cadence startup failed; other startup scripts are unaffected')
        try:
            shutdown()
        except Exception:
            report_failure('Cadence startup cleanup failed')
