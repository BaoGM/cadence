# SPDX-License-Identifier: GPL-3.0-only
import time
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QProgressDialog
from media import Cancelled
from test_drawing import application,window


def test_completed_tasks_release_progress_dialogs(window,application):
    errors=[]; results=[]; window.error=errors.append
    for mode in ['success']*20+['failure','cancel']*4:
        def work(progress,cancel):
            progress(50,'Test')
            if mode=='failure': raise ValueError('expected failure')
            if mode=='cancel': raise Cancelled()
            return 42
        window.begin_task('Test',work,results.append)
        deadline=time.monotonic()+5
        while window.job and time.monotonic()<deadline:
            application.processEvents(); time.sleep(.002)
        assert window.job is None and window.dialog is None
        application.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        assert not window.findChildren(QProgressDialog)
    assert results==[42]*20 and errors==['expected failure']*4
