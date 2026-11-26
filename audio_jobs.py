# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QObject,Signal,Slot
from engine import Task
from audio_prepare import prepare_audio


class AudioJobs(QObject):
    ready=Signal(object)
    failed=Signal(str)
    status=Signal(str)
    def __init__(self,parent=None):
        super().__init__(parent); self.pending={}; self.active=None; self.closing=False
        self.worker=Task(parent=self)
        self.worker.progress.connect(self.progress_changed)
        self.worker.result.connect(self.completed)
        self.worker.failed.connect(self.failed_task)
        self.worker.finished.connect(self.finished)
    def set_media(self,media):
        self.pending={m['audio']:dict(m) for m in media if m.get('audio_pending')}
        if self.active and self.active[0] not in self.pending: self.active[1].cancel.set()
        self.start_next()
    def start_next(self):
        if self.active or self.closing: return
        if not self.pending: self.status.emit(''); return
        path,data=next(iter(self.pending.items()))
        self.active=(path,self.worker)
        self.status.emit('Audio 0 %')
        self.worker.start_work(lambda p,c:prepare_audio(data,p,c),'Audio preparation')
    @Slot(float,str)
    def progress_changed(self,value,message):
        if self.active and self.active[0] in self.pending: self.status.emit(f'Audio {round(value*100)} %')
    @Slot(object)
    def completed(self,result):
        if not self.closing and self.active and self.active[0] in self.pending:
            self.pending.pop(self.active[0],None); self.ready.emit(result)
    @Slot(str)
    def failed_task(self,message):
        if not self.closing and self.active and self.active[0] in self.pending:
            self.pending.pop(self.active[0],None); self.failed.emit(message)
    @Slot()
    def finished(self):
        self.worker.wait()
        self.active=None
        self.start_next()
    def stop(self):
        self.closing=True; self.pending.clear()
        if self.active: self.active[1].cancel.set(); self.active[1].wait()
