# SPDX-License-Identifier: GPL-3.0-only
import faulthandler
import atexit
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import sys
import threading
import time

_ready=False
_fault_file=None

class DiagnosticFormatter(logging.Formatter):
    def __init__(self):
        super().__init__('%(asctime)s %(levelname)s [%(process)d:%(threadName)s] %(message)s')
        profile = str(Path.home()).rstrip('\\/')
        self.profile = re.compile(
            re.escape(profile).replace(r'\\', r'[\\/]') + r'(?=[\\/])', re.IGNORECASE
        ) if profile else None

    def format(self, record):
        message = super().format(record)
        return self.profile.sub('~', message) if self.profile else message

class DiagnosticHandler(RotatingFileHandler):
    def doRollover(self):
        try: super().doRollover()
        except OSError:
            # Another Cadence process may keep the current Windows log open.
            if self.stream is None: self.stream=self._open()

def log_directory():
    if os.environ.get('CADENCE_PREFS'): return Path(os.environ['CADENCE_PREFS']).parent/'logs'
    if os.environ.get('CADENCE_CACHE'): return Path(os.environ['CADENCE_CACHE']).parent/'logs'
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'CadenceStudio-2'/'logs'

def initialize(version=None):
    global _ready,_fault_file
    if _ready: return
    directory=log_directory(); directory.mkdir(parents=True,exist_ok=True)
    handler=DiagnosticHandler(directory/'cadence.log',maxBytes=2*1024*1024,backupCount=3,encoding='utf-8')
    handler.setFormatter(DiagnosticFormatter())
    root=logging.getLogger(); root.setLevel(logging.INFO); root.addHandler(handler)
    logging.captureWarnings(True)
    sys.excepthook=lambda kind,value,tb:logging.critical('Unhandled exception',exc_info=(kind,value,tb))
    threading.excepthook=lambda args:logging.error('Thread failure: %s',args.thread.name if args.thread else '?',exc_info=(args.exc_type,args.exc_value,args.exc_traceback))
    sys.unraisablehook=lambda args:logging.error('Unraisable exception: %s',args.err_msg or repr(args.object),exc_info=(args.exc_type,args.exc_value,args.exc_traceback))
    faults=directory/f'faults-{os.getpid()}.log'
    _fault_file=faults.open('a',encoding='utf-8')
    faulthandler.enable(_fault_file,all_threads=True)
    faulthandler.dump_traceback_later(8,repeat=True,file=_fault_file)
    session_start = time.monotonic()
    def close_faults():
        logging.info('Session ended: runtime=%.1fs', time.monotonic()-session_start)
        faulthandler.cancel_dump_traceback_later(); faulthandler.disable(); _fault_file.close()
        try:
            if faults.stat().st_size==0: faults.unlink()
        except OSError: pass
    atexit.register(close_faults)
    _ready=True
    os_version = sys.getwindowsversion().build if os.name == 'nt' else sys.platform
    logging.info('Startup process: Cadence=%s os=%s build=%s executable=%s frozen=%s Python=%s native_faults=%s',
                 version or 'unknown',sys.platform,os_version,sys.executable,getattr(sys,'frozen',False),
                 sys.version.split()[0],faults.name)

def startup_ready(start):
    if _ready: faulthandler.cancel_dump_traceback_later()
    logging.info('Startup event loop ready: %.3fs',time.perf_counter()-start)

class StartupTimer:
    def __init__(self): self.stamp=time.perf_counter()
    def checkpoint(self,name):
        now=time.perf_counter(); logging.info('Startup %s: %.3fs',name,now-self.stamp); self.stamp=now

def install_qt_logging():
    from PySide6 import __version__ as pyside_version
    from PySide6.QtCore import qInstallMessageHandler,QtMsgType,qVersion
    logging.info('GUI runtime: Qt=%s PySide=%s',qVersion(),pyside_version)
    levels={QtMsgType.QtWarningMsg:logging.WARNING,QtMsgType.QtCriticalMsg:logging.ERROR,QtMsgType.QtFatalMsg:logging.CRITICAL}
    def receive(kind,context,message):
        if kind in levels: logging.log(levels[kind],'Qt: %s',message)
    qInstallMessageHandler(receive)
