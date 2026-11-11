# SPDX-License-Identifier: GPL-3.0-only
import os,subprocess,sys
from pathlib import Path

def test_python_thread_and_qt_errors_are_logged(tmp_path):
    source=Path(__file__).parent
    program='''
import diagnostics,sys,threading,logging
diagnostics.initialize()
try: raise ValueError('main-test')
except Exception: sys.excepthook(*sys.exc_info())
def crash(): raise RuntimeError('thread-test')
thread=threading.Thread(target=crash);thread.start();thread.join()
from PySide6.QtCore import qWarning
diagnostics.install_qt_logging();qWarning('qt-test')
diagnostics.startup_ready(__import__('time').perf_counter())
logging.shutdown()
'''
    env=dict(os.environ,PYTHONPATH=str(source),CADENCE_PREFS=str(tmp_path/'preferences.json'))
    result=subprocess.run([sys.executable,'-c',program],env=env,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    log=(tmp_path/'logs/cadence.log').read_text(encoding='utf-8')
    assert all(text in log for text in ('main-test','thread-test','qt-test','Traceback','Startup event loop ready'))
