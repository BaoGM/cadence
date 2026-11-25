# SPDX-License-Identifier: GPL-3.0-only
import logging
import os
import sys
import threading
import tempfile
import time

from PySide6.QtCore import QObject, Signal, QTimer, Qt
from PySide6.QtWidgets import QMessageBox
from ui_text import tr
from updates import check, download, package_descriptor, UpdateCancelled
from update_store import base_executable, elevated_process, shared_install, read_state, stage, spawn, STORE

class UpdateManager(QObject):
    finished = Signal(object, str)

    def __init__(self, window, version):
        super().__init__(window)
        self.window = window
        self.version = version
        self.base=base_executable()
        self.machine=None
        self.activation_pending=False
        self.ready_button=None
        self.busy = False
        self.manual = False
        self.phase = ''
        self.cancel = threading.Event()
        self.stopped = False
        self.check_timer=QTimer(self)
        self.check_timer.setSingleShot(True)
        self.check_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.check_timer.timeout.connect(self.automatic_check)
        self.finished.connect(self.complete)

    def start(self):
        if not getattr(sys, 'frozen', False):
            return
        if os.environ.get('CADENCE_DISABLE_UPDATES')=='1':
            if os.environ.get('CADENCE_MACHINE_TRIAL')=='1' and shared_install(self.base) and self.machine_available():
                self.machine.send('STATUS')
            return
        if shared_install(self.base):
            if self.activation_pending: return
            if self.machine_available():
                if os.environ.pop('CADENCE_MACHINE_RESTORED','')=='1':
                    self.machine.message(tr('La version précédente de Cadence a été restaurée.'),True)
                self.machine.send('STATUS')
                self.check_timer.start(8000)
            return
        if os.environ.pop('CADENCE_UPDATE_ERROR',''):
            QMessageBox.warning(self.window,tr('Mises à jour'),tr('La mise à jour n’a pas pu être appliquée. Fermez les autres fenêtres de Cadence puis réessayez.'))
        try:
            pending=read_state(self.base.parent/STORE).get('pending')
            if pending and pending!=self.version:
                self.show_ready(pending); return
        except (ValueError,OSError): logging.exception('Cannot read pending update')
        self.check_timer.start(8000)

    def seconds_until_check(self):
        try: elapsed=time.time()-float(self.window.settings.value('updates/last_check',0))
        except (ValueError,TypeError): return 0
        return 86400-elapsed if 0<=elapsed<86400 else 0

    def automatic_check(self):
        if self.stopped: return
        self.check_now(False)
        # Re-evaluate the wall clock after sleep and honour changes to preferences during the session.
        delay=min(3600,self.seconds_until_check() or 3600)
        self.check_timer.start(max(1000,round(delay*1000)))

    def machine_available(self):
        if elevated_process(): return False
        if self.machine is None:
            from update_machine import MachineUpdates,configured
            if not configured(self.base): return False
            self.machine=MachineUpdates(self)
        return True

    def check_now(self, manual=True):
        if self.stopped or self.busy or self.activation_pending:
            return
        if not manual:
            if not self.window.preferences.get('auto_update_check', True):
                return
            if self.seconds_until_check():
                return
        if shared_install(self.base):
            if self.machine_available():
                if self.ready_button is not None:
                    if manual:
                        self.ready_prompt.show(); self.ready_prompt.raise_()
                else:
                    self.machine.check(manual,self.window.preferences.get('update_previews',True))
                return
            if manual:
                from update_machine import install_paths
                try: canonical=self.base==install_paths()[0]
                except OSError: canonical=False
                if elevated_process(): message=tr('Relancez Cadence sans élévation pour rechercher une mise à jour.')
                elif canonical:
                    from maintenance_activation import available,service_exists
                    if available(self.base,self.version):
                        self.offer_maintenance(); return
                    try: installed=service_exists()
                    except OSError: installed=True
                    if installed: message=tr('Le service de maintenance est indisponible. Réessayez plus tard.')
                    else: message=tr('Cette installation est protégée. Demandez à votre administrateur d’activer la maintenance dans l’installateur de Cadence.')
                else: message=tr('Cette installation est protégée. Demandez sa mise à jour à votre administrateur.')
                QMessageBox.information(self.window,tr('Mises à jour'),message)
            return
        if self.ready_button is not None:
            if manual:
                self.ready_prompt.show()
                self.ready_prompt.raise_()
            return
        self.manual = manual
        self.phase = 'check'
        previews = self.window.preferences.get('update_previews', True)
        self.run(lambda: check(self.version, False, previews))

    def offer_maintenance(self):
        from maintenance_activation import activate
        prompt=QMessageBox(self.window)
        prompt.setWindowTitle(tr('Mises à jour'))
        prompt.setText(tr('Activer les mises à jour automatiques pour tous les utilisateurs de cet ordinateur ? Windows demandera une autorisation administrateur.'))
        enable=prompt.addButton(tr('Activer les mises à jour…'),QMessageBox.AcceptRole)
        cancel=prompt.addButton(tr('Annuler'),QMessageBox.RejectRole)
        prompt.setDefaultButton(cancel); prompt.exec()
        if prompt.clickedButton()!=enable: return
        try: launched=activate(self.base,self.version,self.window.winId())
        except OSError:
            QMessageBox.warning(self.window,tr('Mises à jour'),tr('La maintenance n’a pas pu être activée.')); return
        if launched:
            self.activation_pending=True; self.probe_attempts=0
            QTimer.singleShot(1000,self,self.check_activation)

    def check_activation(self):
        if self.stopped: return
        if self.machine_available():
            self.activation_pending=False
            self.check_timer.start(8000)
            self.check_now(True)
            return
        self.probe_attempts+=1
        if self.probe_attempts<60:
            QTimer.singleShot(1000,self,self.check_activation)
        else:
            self.activation_pending=False
            QMessageBox.information(self.window,tr('Mises à jour'),tr('Le service de maintenance est indisponible. Réessayez plus tard.'))

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
        self.ready_prompt=QMessageBox(self.window)
        self.ready_prompt.setWindowTitle(tr('Mises à jour'))
        self.ready_prompt.setText(tr('La mise à jour de Cadence est prête.')+'  '+version)
        self.ready_button=self.ready_prompt.addButton(tr('Redémarrer maintenant'),QMessageBox.AcceptRole)
        later=self.ready_prompt.addButton(tr('Plus tard'),QMessageBox.RejectRole)
        self.ready_prompt.setDefaultButton(later)
        self.ready_button.clicked.connect(self.restart)
        self.ready_prompt.setModal(False)
        self.ready_prompt.show()

    def restart(self):
        if self.window.job: 
            QMessageBox.information(self.window,tr('Mises à jour'),tr('Attendez la fin de la tâche en cours avant d’installer la mise à jour.'))
            return
        if self.machine:
            self.machine.send('APPLY')
            return
        if not self.window.confirm_discard(): return
        self.window._update_close_approved=True
        if self.window.close(): spawn(self.base,[])
        else: self.window._update_close_approved=False

    def restart_machine(self):
        if self.window.job or not self.window.confirm_discard(): return
        try: watcher=self.machine.watcher()
        except OSError:
            self.machine.message(tr('Le service de maintenance est indisponible. Réessayez plus tard.'),True)
            return
        self.window._update_close_approved=True
        if not self.window.close():
            self.window._update_close_approved=False
            watcher.terminate()

    def stop(self):
        self.stopped = True; self.check_timer.stop(); self.cancel.set()
        if self.machine: self.machine.poll.stop()

def manager(window, version):
    if not hasattr(window, 'update_manager'):
        window.update_manager = UpdateManager(window, version)
    return window.update_manager
