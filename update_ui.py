# SPDX-License-Identifier: GPL-3.0-only
import logging
import os
from pathlib import Path
import sys
import threading
import time

from PySide6.QtCore import QObject, Signal, QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog
from ui_text import tr, language
from dialogs import ConfirmationDialog
from updates import check, download, verify_package, installed_copy, launch_installer, UpdateCancelled

class UpdateManager(QObject):
    finished = Signal(object, str)
    progress = Signal(int)

    def __init__(self, window, version):
        super().__init__(window)
        self.window = window
        self.version = version
        self.installed = bool(getattr(sys, 'frozen', False)) and installed_copy(sys.executable)
        self.busy = False
        self.manual = False
        self.phase = ''
        self.cancel = threading.Event()
        self.pending = None
        self.dialog = None
        self.stopped = False
        self.finished.connect(self.complete)
        self.progress.connect(self.update_progress)
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.timeout.connect(self.offer_pending)

    def start(self):
        if not getattr(sys, 'frozen', False) or os.environ.get('CADENCE_DISABLE_UPDATES') == '1':
            return
        QTimer.singleShot(8000, self, lambda: self.check_now(False))

    def check_now(self, manual=True):
        if self.stopped or self.busy or self.pending is not None:
            return
        if not manual:
            if not self.window.preferences.get('auto_update_check', True):
                return
            try: elapsed = time.time() - float(self.window.settings.value('updates/last_check', 0))
            except (ValueError, TypeError): elapsed = 86400
            if 0 <= elapsed < 86400:
                return
        self.manual = manual
        self.phase = 'check'
        previews = self.window.preferences.get('update_previews', False)
        self.run(lambda: check(self.version, self.installed, previews))

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

    def update_progress(self, value):
        if self.dialog is not None and not self.cancel.is_set():
            self.dialog.setValue(min(99, value))

    def complete(self, result, error):
        self.busy = False
        if self.dialog is not None:
            self.dialog.canceled.disconnect(self.cancel.set)
            self.dialog.close(); self.dialog.deleteLater(); self.dialog = None
        if self.stopped:
            return
        if error:
            if error != 'cancelled' and (self.manual or self.phase == 'download'):
                QMessageBox.warning(self.window, tr('Mises à jour'), tr('La mise à jour n’a pas pu être vérifiée ou téléchargée. Réessayez plus tard. Les détails figurent dans le journal.'))
            return
        if self.phase == 'check':
            self.window.settings.setValue('updates/last_check', time.time())
            if result is None:
                if self.manual:
                    message = QMessageBox(self.window)
                    message.setWindowTitle(tr('Mises à jour'))
                    message.setText(tr('Aucune nouvelle version disponible.'))
                    message.setStandardButtons(QMessageBox.StandardButton.Ok)
                    message.exec()
                return
            self.pending = result; self.timer.start(0)
        else:
            if self.cancel.is_set():
                return
            self.install_offer(*result)

    def offer_pending(self):
        if self.stopped or self.pending is None:
            return
        if QApplication.activeModalWidget() is not None or self.window.job or self.window.timer.isActive() or self.window.isMinimized():
            self.timer.start(1000); return
        if not self.manual and not self.window.preferences.get('auto_update_check', True):
            self.pending = None; return
        release, self.pending = self.pending, None
        description = tr('Préversion') if release.prerelease else tr('Version')
        unit = 'Mo' if language() == 'fr' else 'MB'
        detail = f'Cadence {release.version} - {description}\n{release.size/1024**2:.1f} {unit}'
        detail += '\n' + (tr('L’installation sera proposée après vérification du téléchargement.') if self.installed else tr('Version portable : l’archive sera téléchargée, puis vous pourrez l’extraire dans un nouveau dossier.'))
        box = ConfirmationDialog(self.window, tr('Mise à jour disponible'), tr('Télécharger cette mise à jour ?'), detail)
        if box.exec() != 1:
            return
        self.phase = 'download'
        root = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CadenceStudio' / 'updates'
        self.dialog = QProgressDialog(tr('Téléchargement de la mise à jour…'), tr('Annuler'), 0, 100, self.window)
        self.dialog.setWindowTitle(tr('Mises à jour')); self.dialog.setAutoClose(False); self.dialog.setMinimumDuration(0)
        self.dialog.setWindowModality(Qt.WindowModality.NonModal); self.dialog.canceled.connect(self.cancel.set); self.dialog.show()
        self.run(lambda: download(release, root, self.cancel, self.progress.emit))

    def install_offer(self, path, digest):
        if not self.installed:
            QMessageBox.information(self.window, tr('Mises à jour'), tr('Archive portable vérifiée. Extrayez-la dans un nouveau dossier, puis lancez Cadence.exe. Vos préférences sont conservées.'))
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
            return
        box = ConfirmationDialog(self.window, tr('Mises à jour'), tr('Installer la mise à jour maintenant ?'), tr('Cadence doit être fermé. Vous pourrez enregistrer votre projet avant de continuer. Windows peut demander une autorisation.'))
        if box.exec() != 1:
            return
        if self.window.job:
            QMessageBox.information(self.window, tr('Mises à jour'), tr('Attendez la fin de la tâche en cours avant d’installer la mise à jour.'))
            return
        if not self.window.confirm_discard():
            return
        try:
            verify_package(path, digest)
            launch_installer(path, Path(sys.executable).resolve().parent)
        except (OSError, ValueError):
            logging.exception('Update installer could not start')
            QMessageBox.warning(self.window, tr('Mises à jour'), tr('L’installateur n’a pas été lancé. Cadence reste ouvert.'))
            return
        self.window._update_close_approved = True
        self.window.close()

    def stop(self):
        self.stopped = True; self.cancel.set(); self.timer.stop(); self.pending = None

def manager(window, version):
    if not hasattr(window, 'update_manager'):
        window.update_manager = UpdateManager(window, version)
    return window.update_manager
