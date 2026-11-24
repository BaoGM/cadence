# SPDX-License-Identifier: GPL-3.0-only
import logging
import os
import sys
import threading
import tempfile
import time

from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtWidgets import QMessageBox, QPushButton
from ui_text import tr
from updates import check, download, package_descriptor, UpdateCancelled
from update_store import base_executable, shared_install, read_state, stage, spawn, STORE

class UpdateManager(QObject):
    finished = Signal(object, str)

    def __init__(self, window, version):
        super().__init__(window)
        self.window = window
        self.version = version
        self.base=base_executable()
        self.ready_button=None
        self.busy = False
        self.manual = False
        self.phase = ''
        self.cancel = threading.Event()
        self.stopped = False
        self.finished.connect(self.complete)

    def start(self):
        if not getattr(sys, 'frozen', False) or os.environ.get('CADENCE_DISABLE_UPDATES') == '1':
            return
        try:
            pending=read_state(self.base.parent/STORE).get('pending')
            if pending:
                self.show_ready(pending); return
        except (ValueError,OSError): logging.exception('Cannot read pending update')
        QTimer.singleShot(8000, self, lambda: self.check_now(False))

    def check_now(self, manual=True):
        if self.stopped or self.busy:
            return
        if not manual:
            if not self.window.preferences.get('auto_update_check', True):
                return
            try: elapsed = time.time() - float(self.window.settings.value('updates/last_check', 0))
            except (ValueError, TypeError): elapsed = 86400
            if 0 <= elapsed < 86400:
                return
        if shared_install(self.base):
            if manual: QMessageBox.information(self.window,tr('Mises à jour'),tr('Cette installation est gérée pour tous les utilisateurs. La mise à jour doit être faite par un administrateur.'))
            return
        if self.ready_button is not None: return
        self.manual = manual
        self.phase = 'check'
        previews = self.window.preferences.get('update_previews', True)
        self.run(lambda: check(self.version, False, previews))

    def run(self, operation):
        self.busy = True; self.cancel.clear()
        def work():
            try: result, error = operation(), ''
            except UpdateCancelled: result, error = None, 'cancelled'
            except Exception as exc:
                logging.exception('Update %s failed', self.phase)
                result, error = None, type(exc).__name__
            try: self.finished.emit(result, error)
            except RuntimeError: pass  # The application may have closed during an HTTPS request.
        threading.Thread(target=work, name='Cadence update', daemon=True).start()

    def complete(self, result, error):
        self.busy=False
        if self.stopped: return
        if error:
            if error!='cancelled' and self.manual:
                QMessageBox.warning(self.window,tr('Mises à jour'),tr('La mise à jour n’a pas pu être vérifiée ou téléchargée. Réessayez plus tard. Les détails figurent dans le journal.'))
            return
        if self.phase=='download':
            if result: self.show_ready(result)
            return
        self.window.settings.setValue('updates/last_check',time.time())
        if result is None:
            if self.manual: QMessageBox.information(self.window,tr('Mises à jour'),tr('Aucune nouvelle version disponible.'))
            return
        if not self.manual and not self.window.preferences.get('auto_update_check',True): return
        self.phase='download'
        def prepare():
            store=self.base.parent/STORE
            if read_state(store).get('failed')==result.version: return None
            store.mkdir(exist_ok=True)
            manifest=package_descriptor(result)
            with tempfile.TemporaryDirectory(dir=store) as directory:
                path,digest=download(result,directory,self.cancel,lambda p:None,manifest)
                return stage(self.base,result,path,digest,manifest,self.cancel)
        self.run(prepare)

    def show_ready(self,version):
        if self.ready_button is not None: return
        self.ready_button=QPushButton(tr('Mise à jour prête · Redémarrer maintenant'),self.window)
        self.ready_button.setToolTip('Cadence '+version)
        self.ready_button.clicked.connect(self.restart)
        self.window.statusBar().addPermanentWidget(self.ready_button)

    def restart(self):
        if self.window.job: 
            QMessageBox.information(self.window,tr('Mises à jour'),tr('Attendez la fin de la tâche en cours avant d’installer la mise à jour.'))
            return
        if not self.window.confirm_discard(): return
        self.window._update_close_approved=True
        if self.window.close(): spawn(self.base,[])
        else: self.window._update_close_approved=False

    def stop(self):
        self.stopped = True; self.cancel.set()

def manager(window, version):
    if not hasattr(window, 'update_manager'):
        window.update_manager = UpdateManager(window, version)
    return window.update_manager
