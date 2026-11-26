# SPDX-License-Identifier: GPL-3.0-only
import logging
import hashlib
import os
import sys
import threading
import time

from PySide6.QtCore import QObject, Signal, QTimer, Qt
from PySide6.QtWidgets import QMessageBox
from ui_text import tr
from updates import check, UpdateCancelled, version_tuple
from update_store import base_executable, elevated_process, machine_install_location, shared_install, read_state, spawn, STORE
from update_user import prepare_as_desktop_user, prepared_as_desktop_user, prepare_package
from update_desktop import launch_as_desktop_user

class UpdateManager(QObject):
    finished = Signal(object, str)

    def __init__(self, window, version):
        super().__init__(window)
        self.window = window
        self.version = version
        self.base=base_executable()
        self.machine=None
        self.user_session_update=False
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
            elif elevated_process():
                self.user_session_update=not self.canonical_install()
                hint=self.window.settings.value(self.portable_hint_key(),'') if self.user_session_update else ''
                if hint:
                    try: newer=version_tuple(hint)>version_tuple(self.version)
                    except ValueError: newer=False
                    if newer:
                        self.phase='probe'
                        self.run(lambda:hint if prepared_as_desktop_user(self.base,hint,self.cancel) else None)
                        return
                    self.window.settings.remove(self.portable_hint_key())
                self.check_timer.start(8000)
            return
        if os.environ.pop('CADENCE_UPDATE_ERROR',''):
            QMessageBox.warning(self.window,tr('Mises à jour'),tr('La mise à jour n’a pas pu être appliquée. Fermez les autres fenêtres de Cadence puis réessayez.'))
        try:
            pending=read_state(self.base.parent/STORE).get('pending')
            if pending and version_tuple(pending)>version_tuple(self.version):
                self.window.settings.setValue(self.portable_hint_key(),pending)
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
        if self.machine is None:
            from update_machine import MachineUpdates,configured
            if not configured(self.base): return False
            self.machine=MachineUpdates(self)
        return True

    def canonical_install(self):
        from update_machine import install_paths
        try: return self.base==install_paths()[0]
        except OSError: return False

    def portable_hint_key(self):
        location=os.path.normcase(str(self.base)).encode('utf-8')
        return 'updates/preparing/'+hashlib.sha256(location).hexdigest()

    def check_now(self, manual=True):
        if self.stopped or self.busy or self.activation_pending:
            return
        if not manual:
            if not self.window.preferences.get('auto_update_check', True):
                return
            if self.seconds_until_check():
                return
        phase='check'
        if shared_install(self.base):
            if self.machine_available():
                if self.ready_button is not None:
                    if manual:
                        self.ready_prompt.show(); self.ready_prompt.raise_()
                else:
                    self.machine.check(manual,self.window.preferences.get('update_previews',True))
                return
            canonical=self.canonical_install()
            elevated=elevated_process()
            self.user_session_update=elevated and not canonical
            if not elevated:
                if manual:
                    if canonical: self.maintenance_options()
                    else: QMessageBox.information(self.window,tr('Mises à jour'),tr('Cette installation est protégée. Demandez sa mise à jour à votre administrateur.'))
                return
            if canonical: phase='discover'
        if self.ready_button is not None:
            if manual:
                self.ready_prompt.show()
                self.ready_prompt.raise_()
            return
        self.manual = manual
        self.phase = phase
        self.previews = self.window.preferences.get('update_previews', True)
        self.run(lambda: check(self.version, False, self.previews))

    def maintenance_options(self, status='', update_available=True):
        from maintenance_activation import available,service_exists
        if available(self.base,self.version):
            self.offer_maintenance(status)
            return
        if update_available:
            try: installed=service_exists()
            except OSError: installed=True
            reason=(tr('Le service de maintenance est indisponible. Réessayez plus tard.') if installed else
                    tr('Cette installation est protégée. Demandez à votre administrateur d’activer la maintenance dans l’installateur de Cadence.'))
            status='\n\n'.join(filter(None,(status,reason)))
        QMessageBox.information(self.window,tr('Mises à jour'),status)

    def offer_maintenance(self, status=''):
        from maintenance_activation import activate
        prompt=QMessageBox(self.window)
        prompt.setWindowTitle(tr('Mises à jour'))
        question=tr('Activer les mises à jour automatiques pour tous les utilisateurs de cet ordinateur ?')
        prompt.setText('\n\n'.join(filter(None,(status,question))))
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
        if self.phase=='probe':
            if result and not error:
                self.show_ready(result)
            else:
                if not error: self.window.settings.remove(self.portable_hint_key())
                self.window.settings.setValue('updates/last_check',0)
                self.check_timer.start(8000)
            return
        if error:
            if self.user_session_update and self.phase=='download' and self.manual and error in ('OSError','PermissionError'):
                QMessageBox.warning(self.window,tr('Mises à jour'),tr('Windows n’a pas pu préparer cette mise à jour dans votre session utilisateur. Vérifiez que votre compte peut modifier le dossier de Cadence.'))
                return
            if error!='cancelled' and self.manual:
                QMessageBox.warning(self.window,tr('Mises à jour'),tr('La mise à jour n’a pas pu être vérifiée ou téléchargée. Réessayez plus tard. Les détails figurent dans le journal.'))
            return
        if self.phase=='download':
            if result: self.show_ready(result)
            else: self.window.settings.remove(self.portable_hint_key())
            return
        self.window.settings.setValue('updates/last_check',time.time())
        if self.phase=='discover':
            if self.manual:
                status=(tr('Une mise à jour est disponible : {version}.').format(version=result.version) if result
                        else tr('Aucune nouvelle version disponible.'))
                self.maintenance_options(status,result is not None)
            return
        if result is None:
            if self.manual: QMessageBox.information(self.window,tr('Mises à jour'),tr('Aucune nouvelle version disponible.'))
            return
        if not self.manual and not self.window.preferences.get('auto_update_check',True): return
        self.phase='download'
        if self.user_session_update and machine_install_location(self.base):
            if self.manual:
                QMessageBox.information(self.window,tr('Mises à jour'),tr('Une mise à jour est disponible : {version}. Demandez à votre administrateur de l’installer dans le dossier partagé.').format(version=result.version))
            return
        self.window.settings.setValue(self.portable_hint_key(),result.version)
        self.window.settings.sync()
        if self.user_session_update:
            self.run(lambda:prepare_as_desktop_user(self.base,result,self.previews,self.cancel))
        else:
            self.run(lambda:prepare_package(self.base,result,self.cancel))

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
        if self.user_session_update:
            try: child=launch_as_desktop_user(self.base,suspended=True)
            except OSError:
                QMessageBox.warning(self.window,tr('Mises à jour'),tr('Windows n’a pas pu redémarrer Cadence dans votre session utilisateur.'))
                return
            self.window._update_close_approved=True
            try:
                if self.window.close():
                    try: child.resume()
                    except OSError:
                        logging.exception('Could not resume Cadence after closing')
                        try: child.terminate()
                        except OSError: logging.exception('Could not terminate the interrupted restart')
                        try: launch_as_desktop_user(self.base).close()
                        except OSError:
                            QMessageBox.warning(None,tr('Mises à jour'),tr('Ouvrez Cadence depuis votre bureau pour terminer la mise à jour.'))
                else:
                    self.window._update_close_approved=False
                    child.terminate()
            finally: child.close()
            return
        self.window._update_close_approved=True
        if self.window.close(): spawn(self.base,[])
        else: self.window._update_close_approved=False

    def restart_machine(self):
        if self.window.job or not self.window.confirm_discard(): return
        from update_machine import MaintenanceUnavailable
        try: watcher=self.machine.watcher()
        except MaintenanceUnavailable:
            self.machine.message(tr('Le service de maintenance est indisponible. Réessayez plus tard.'),True)
            return
        except OSError:
            logging.exception('Windows could not launch the Cadence restart helper')
            self.machine.message(tr('Windows n’a pas pu redémarrer Cadence dans votre session utilisateur.')+' '+
                                 tr('Ouvrez Cadence depuis votre bureau pour terminer la mise à jour.'),True)
            return
        self.window._update_close_approved=True
        try:
            if not self.window.close():
                self.window._update_close_approved=False
                watcher.terminate()
        finally:
            if hasattr(watcher,'close'): watcher.close()

    def stop(self):
        self.stopped = True; self.check_timer.stop(); self.cancel.set()
        if self.machine: self.machine.poll.stop()

def manager(window, version):
    if not hasattr(window, 'update_manager'):
        window.update_manager = UpdateManager(window, version)
    return window.update_manager
