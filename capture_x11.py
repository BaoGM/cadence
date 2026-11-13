# SPDX-License-Identifier: GPL-3.0-only
import ctypes as C
import logging
import os

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication


def available():
    app = QApplication.instance()
    return bool(app and app.platformName() == 'xcb' and os.environ.get('DISPLAY')
                and os.environ.get('XDG_SESSION_TYPE') != 'wayland' and not os.environ.get('WAYLAND_DISPLAY'))


class KeyEvent(C.Structure):
    _fields_ = [('type', C.c_int), ('serial', C.c_ulong), ('send_event', C.c_int),
               ('display', C.c_void_p), ('window', C.c_ulong), ('root', C.c_ulong),
               ('subwindow', C.c_ulong), ('time', C.c_ulong), ('x', C.c_int), ('y', C.c_int),
               ('x_root', C.c_int), ('y_root', C.c_int), ('state', C.c_uint),
               ('keycode', C.c_uint), ('same_screen', C.c_int)]


class XEvent(C.Union):
    _fields_ = [('type', C.c_int), ('key', KeyEvent), ('pad', C.c_long * 24)]


class Monitor(C.Structure):
    _fields_ = [('name', C.c_ulong), ('primary', C.c_int), ('automatic', C.c_int),
               ('noutput', C.c_int), ('x', C.c_int), ('y', C.c_int), ('width', C.c_int),
               ('height', C.c_int), ('mwidth', C.c_int), ('mheight', C.c_int),
               ('outputs', C.POINTER(C.c_ulong))]


class Connection:
    def __init__(self):
        self.x = C.CDLL('libX11.so.6')
        signatures = {
            'XOpenDisplay': ([C.c_char_p], C.c_void_p),
            'XCloseDisplay': ([C.c_void_p], C.c_int),
            'XDefaultRootWindow': ([C.c_void_p], C.c_ulong),
            'XKeysymToKeycode': ([C.c_void_p, C.c_ulong], C.c_uint),
            'XkbKeycodeToKeysym': ([C.c_void_p, C.c_uint, C.c_int, C.c_int], C.c_ulong),
            'XKeysymToString': ([C.c_ulong], C.c_char_p),
            'XQueryKeymap': ([C.c_void_p, C.c_void_p], C.c_int),
            'XQueryPointer': ([C.c_void_p, C.c_ulong, C.POINTER(C.c_ulong), C.POINTER(C.c_ulong),
                               *[C.POINTER(C.c_int)] * 4, C.POINTER(C.c_uint)], C.c_int),
            'XGrabKey': ([C.c_void_p, C.c_int, C.c_uint, C.c_ulong, C.c_int, C.c_int, C.c_int], C.c_int),
            'XUngrabKey': ([C.c_void_p, C.c_int, C.c_uint, C.c_ulong], C.c_int),
            'XSync': ([C.c_void_p, C.c_int], C.c_int),
            'XSetErrorHandler': ([C.c_void_p], C.c_void_p),
            'XPending': ([C.c_void_p], C.c_int),
            'XNextEvent': ([C.c_void_p, C.POINTER(XEvent)], C.c_int),
            'XkbSetDetectableAutoRepeat': ([C.c_void_p, C.c_int, C.POINTER(C.c_int)], C.c_int),
            'XGetAtomName': ([C.c_void_p, C.c_ulong], C.c_void_p),
            'XFree': ([C.c_void_p], C.c_int),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.x, name); fn.argtypes = args; fn.restype = result
        self.display = self.x.XOpenDisplay(None)
        if not self.display: raise RuntimeError('Écran X11 indisponible.')
        self.root = self.x.XDefaultRootWindow(self.display)

    def close(self):
        if self.display:
            self.x.XCloseDisplay(self.display); self.display = None


def monitors():
    connection = Connection()
    try:
        randr = C.CDLL('libXrandr.so.2')
        randr.XRRGetMonitors.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.POINTER(C.c_int)]
        randr.XRRGetMonitors.restype = C.POINTER(Monitor)
        randr.XRRFreeMonitors.argtypes = [C.POINTER(Monitor)]
        count = C.c_int()
        entries = randr.XRRGetMonitors(connection.display, connection.root, 1, C.byref(count))
        result = {}
        try:
            for index in range(count.value):
                item = entries[index]
                atom = connection.x.XGetAtomName(connection.display, item.name)
                if atom:
                    try: result[C.string_at(atom).decode()] = (item.x, item.y, item.width, item.height)
                    finally: connection.x.XFree(atom)
        finally:
            if entries: randr.XRRFreeMonitors(entries)
        return result
    finally: connection.close()


class Hotkey:
    def __init__(self, callback):
        self.callback = callback; self.connection = None; self.pressed = False
        self.timer = QTimer(); self.timer.setInterval(20); self.timer.timeout.connect(self.poll)

    def register(self):
        if self.connection: return True
        if not available(): return False
        try:
            conn = Connection(); x, display = conn.x, conn.display
            key = x.XKeysymToKeycode(display, 0xffc5)  # F8; tolerate Caps Lock and Num Lock.
            errors = []
            handler_type = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_void_p)
            def error(dpy, event):
                if dpy == display: errors.append(True); return 0
                return handler_type(previous)(dpy, event) if previous else 0
            handler = handler_type(error)
            x.XSync(display, 0)
            previous = x.XSetErrorHandler(C.cast(handler, C.c_void_p))
            try:
                for locks in (0, 2, 16, 18): x.XGrabKey(display, key, 5 | locks, conn.root, 0, 1, 1)
                x.XSync(display, 0)
            finally: x.XSetErrorHandler(previous)
            if errors: conn.close(); return False
            supported = C.c_int()
            x.XkbSetDetectableAutoRepeat(display, 1, C.byref(supported))
            self.connection = conn; self.key = key; self.timer.start()
            return True
        except (OSError, RuntimeError):
            logging.exception('X11 capture shortcut unavailable')
            return False

    def poll(self):
        conn = self.connection
        if not conn: return
        event = XEvent()
        while conn.x.XPending(conn.display):
            conn.x.XNextEvent(conn.display, C.byref(event))
            if event.type == 2 and event.key.keycode == self.key and not self.pressed:
                self.pressed = True; QTimer.singleShot(0, self.callback)
            elif event.type == 3 and event.key.keycode == self.key: self.pressed = False

    def close(self):
        self.timer.stop()
        if self.connection: self.connection.close(); self.connection = None
        self.pressed = False


class Inputs:
    def __init__(self):
        self.connection = Connection(); self.names = {}

    def close(self): self.connection.close()

    def pressed(self, keyboard):
        conn = self.connection; keys = set(); bitmap = (C.c_ubyte * 32)()
        if keyboard:
            conn.x.XQueryKeymap(conn.display, bitmap)
            aliases = {0xffe1:16, 0xffe2:16, 0xffe3:17, 0xffe4:17, 0xffe9:18, 0xffea:18, 0xffeb:91, 0xffec:91}
            for code in range(8, 256):
                if bitmap[code // 8] & (1 << (code % 8)):
                    symbol = conn.x.XkbKeycodeToKeysym(conn.display, code, 0, 0)
                    key = aliases.get(symbol, code + 256)
                    raw = conn.x.XKeysymToString(symbol)
                    if raw: self.names[key] = raw.decode(errors='replace')
                    keys.add(key)
        root, child = C.c_ulong(), C.c_ulong()
        rx, ry, wx, wy, mask = C.c_int(), C.c_int(), C.c_int(), C.c_int(), C.c_uint()
        conn.x.XQueryPointer(conn.display, conn.root, C.byref(root), C.byref(child), C.byref(rx), C.byref(ry), C.byref(wx), C.byref(wy), C.byref(mask))
        for flag, key in ((256, 1), (512, 4), (1024, 2)):
            if mask.value & flag: keys.add(key)
        return keys

    def name(self, key):
        from ui_text import tr
        fixed = {16:'Maj', 17:'Ctrl', 18:'Alt', 91:'Super'}
        if key in fixed: return tr(fixed[key])
        value = self.names.get(key, '')
        aliases = {'space':'Espace', 'Return':'Entrée', 'Escape':'Échap', 'BackSpace':'Retour arrière',
                   'Delete':'Suppr', 'Left':'←', 'Up':'↑', 'Right':'→', 'Down':'↓'}
        return tr(aliases[value]) if value in aliases else value.upper() if len(value) == 1 else value.replace('_', ' ')
