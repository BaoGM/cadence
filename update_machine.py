# SPDX-License-Identifier: GPL-3.0-only
import ctypes
from ctypes import wintypes as wt
import json
from pathlib import Path
import subprocess
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QMessageBox

from ui_text import tr
from updates import version_tuple
from maintenance_identity import identify_installed_process,install_paths


SERVICE='CadenceStudio2Maintenance'
PIPE=r'\\.\pipe\CadenceStudio2Maintenance.v1'
COMMANDS={'STATUS','CHECK_STABLE','CHECK_PREVIEW','APPLY','READY'}
STATES={'idle','checking','downloading','ready','waiting','applying','trial','installed','rollback','failed'}


def configured(base):
    try:
        app,helper=install_paths()
        return Path(base)==app and helper.is_file() and service_pid()>0 and identify_installed_process()
    except OSError: return False


def service_pid():
    api=ctypes.WinDLL('advapi32',use_last_error=True)
    api.OpenSCManagerW.argtypes=[wt.LPCWSTR,wt.LPCWSTR,wt.DWORD]; api.OpenSCManagerW.restype=wt.HANDLE
    api.OpenServiceW.argtypes=[wt.HANDLE,wt.LPCWSTR,wt.DWORD]; api.OpenServiceW.restype=wt.HANDLE
    api.CloseServiceHandle.argtypes=[wt.HANDLE]
    api.QueryServiceStatusEx.argtypes=[wt.HANDLE,ctypes.c_int,wt.LPVOID,wt.DWORD,ctypes.POINTER(wt.DWORD)]
    scm=api.OpenSCManagerW(None,None,1)
    if not scm: raise ctypes.WinError(ctypes.get_last_error())
    try:
        service=api.OpenServiceW(scm,SERVICE,4)
        if not service: raise ctypes.WinError(ctypes.get_last_error())
        try:
            status=(wt.DWORD*9)(); needed=wt.DWORD()
            if not api.QueryServiceStatusEx(service,0,status,ctypes.sizeof(status),ctypes.byref(needed)):
                raise ctypes.WinError(ctypes.get_last_error())
            return status[7] if status[1]==4 else 0
        finally: api.CloseServiceHandle(service)
    finally: api.CloseServiceHandle(scm)


class Overlapped(ctypes.Structure):
    _fields_=[('internal',ctypes.c_size_t),('high',ctypes.c_size_t),
              ('offset',wt.DWORD),('offset_high',wt.DWORD),('event',wt.HANDLE)]


def request(command):
    if command not in COMMANDS: raise ValueError('Invalid maintenance command')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[wt.LPCWSTR,wt.DWORD,wt.DWORD,wt.LPVOID,wt.DWORD,wt.DWORD,wt.HANDLE]
    kernel.CreateFileW.restype=wt.HANDLE
    kernel.CreateEventW.argtypes=[wt.LPVOID,wt.BOOL,wt.BOOL,wt.LPCWSTR]; kernel.CreateEventW.restype=wt.HANDLE
    kernel.WaitNamedPipeW.argtypes=[wt.LPCWSTR,wt.DWORD]
    kernel.CloseHandle.argtypes=[wt.HANDLE]
    kernel.WaitForSingleObject.argtypes=[wt.HANDLE,wt.DWORD]
    kernel.GetNamedPipeServerProcessId.argtypes=[wt.HANDLE,ctypes.POINTER(wt.DWORD)]
    kernel.CancelIoEx.argtypes=[wt.HANDLE,ctypes.POINTER(Overlapped)]
    kernel.GetOverlappedResult.argtypes=[wt.HANDLE,ctypes.POINTER(Overlapped),ctypes.POINTER(wt.DWORD),wt.BOOL]
    server=service_pid()
    if not server: raise OSError('Maintenance service unavailable')
    if not kernel.WaitNamedPipeW(PIPE,2000): raise ctypes.WinError(ctypes.get_last_error())
    handle=kernel.CreateFileW(PIPE,3,0,None,3,0x40000000|0x00100000|0x00010000,None)
    if handle==wt.HANDLE(-1).value: raise ctypes.WinError(ctypes.get_last_error())
    deadline=time.monotonic()+3
    def transfer(operation,buffer,length):
        operation.argtypes=[wt.HANDLE,wt.LPVOID,wt.DWORD,ctypes.POINTER(wt.DWORD),ctypes.POINTER(Overlapped)]
        event=kernel.CreateEventW(None,True,False,None)
        if not event: raise ctypes.WinError(ctypes.get_last_error())
        try:
            io=Overlapped(event=event); count=wt.DWORD()
            if not operation(handle,buffer,length,ctypes.byref(count),ctypes.byref(io)):
                error=ctypes.get_last_error()
                if error!=997: raise ctypes.WinError(error)
                if kernel.WaitForSingleObject(event,max(0,round((deadline-time.monotonic())*1000)))!=0:
                    kernel.CancelIoEx(handle,ctypes.byref(io))
                    kernel.GetOverlappedResult(handle,ctypes.byref(io),ctypes.byref(count),True)
                    raise TimeoutError('Maintenance service timeout')
                if not kernel.GetOverlappedResult(handle,ctypes.byref(io),ctypes.byref(count),False):
                    raise ctypes.WinError(ctypes.get_last_error())
            return count.value
        finally: kernel.CloseHandle(event)
    try:
        pid=wt.DWORD()
        if not kernel.GetNamedPipeServerProcessId(handle,ctypes.byref(pid)) or pid.value!=server:
            raise OSError('Unexpected maintenance service')
        data=(command+'\n').encode('ascii')
        if transfer(kernel.WriteFile,ctypes.create_string_buffer(data),len(data))!=len(data):
            raise OSError('Incomplete maintenance request')
        response=bytearray()
        while not response.endswith(b'\n'):
            remaining=512-len(response)
            if not remaining: raise ValueError('Oversized maintenance status')
            buffer=ctypes.create_string_buffer(remaining)
            received=transfer(kernel.ReadFile,buffer,remaining)
            if not received: raise OSError('Incomplete maintenance status')
            response.extend(buffer.raw[:received])
        if pid.value!=service_pid(): raise OSError('Maintenance service restarted')
    finally: kernel.CloseHandle(handle)
    status=json.loads(response.decode('ascii'))
    if (not isinstance(status,dict) or status.get('state') not in STATES or
            type(status.get('progress')) is not int or not 0<=status['progress']<=100 or
            not isinstance(status.get('version'),str) or type(status.get('blocked',False)) is not bool):
        raise ValueError('Invalid maintenance status')
    if status['version']: version_tuple(status['version'])
    return status


class MachineUpdates(QObject):
    finished=Signal(str,object)

    def __init__(self,manager):
        super().__init__(manager)
        self.manager=manager
        self.poll=QTimer(self); self.poll.setSingleShot(True)
        self.poll.timeout.connect(lambda:self.send('STATUS'))
        self.finished.connect(self.complete)
        self.busy=False; self.pending=None; self.manual=False; self.saw_rollback=False

    def send(self,command):
        if self.manager.stopped: return
        if self.busy:
            if command!='STATUS' and self.pending not in ('APPLY','READY'): self.pending=command
            return
        self.busy=True
        def work():
            try: result=request(command)
            except (OSError,ValueError): result=None
            try: self.finished.emit(command,result)
            except RuntimeError: pass
        threading.Thread(target=work,name='Cadence maintenance',daemon=True).start()

    def message(self,text,warning=False):
        box=QMessageBox(self.manager.window)
        box.setWindowTitle(tr('Mises à jour')); box.setText(text)
        box.setIcon(QMessageBox.Warning if warning else QMessageBox.Information)
        box.setAttribute(Qt.WA_DeleteOnClose)
        box.setModal(False); box.show()

    def check(self,manual,previews):
        self.manual|=manual
        self.send('CHECK_PREVIEW' if previews else 'CHECK_STABLE')

    def complete(self,command,status):
        self.busy=False
        if self.manager.stopped: return
        if not status:
            if self.manual or command=='APPLY':
                self.message(tr('Le service de maintenance est indisponible. Réessayez plus tard.'),True)
            self.manual=False
        else:
            state=status['state']; version=status['version']
            if command.startswith('CHECK_') and state!='failed':
                self.manager.window.settings.setValue('updates/last_check',time.time())
            if command=='APPLY' and status.get('blocked'):
                self.message(tr('Fermez les autres instances de Cadence pour appliquer la mise à jour.'))
            elif command=='APPLY' and state in ('waiting','applying'):
                self.manager.restart_machine()
            elif state=='trial' and version==self.manager.version and command!='READY':
                self.send('READY')
            elif state in ('checking','downloading','applying') or state=='trial' and command=='READY':
                self.poll.start(1500)
            elif state in ('ready','waiting') and version!=self.manager.version:
                self.manager.show_ready(version)
            elif state=='rollback' and not self.saw_rollback:
                self.saw_rollback=True; self.message(tr('Fermez Cadence pour permettre la restauration de la version précédente.'),True)
            elif self.manual and state=='failed':
                self.message(tr('La mise à jour n’a pas pu être vérifiée ou téléchargée. Réessayez plus tard. Les détails figurent dans le journal.'),True)
            elif self.manual and state in ('idle','installed'):
                self.message(tr('Aucune nouvelle version disponible.'))
            if state not in ('checking','downloading'): self.manual=False
        if self.pending:
            command=self.pending; self.pending=None
            self.send(command)

    def watcher(self):
        if not configured(self.manager.base): raise OSError('Maintenance service unavailable')
        app,helper=install_paths()
        return subprocess.Popen([str(helper)],cwd=str(helper.parent),creationflags=subprocess.CREATE_NO_WINDOW)
