# SPDX-License-Identifier: GPL-3.0-only
import time
import pytest
from PySide6.QtCore import QEventLoop,QTimer
from PySide6.QtWidgets import QApplication,QWidget
import video_surface


@pytest.fixture
def viewer(monkeypatch):
    monkeypatch.setenv('CADENCE_RENDERER','software')
    app=QApplication.instance() or QApplication([])
    widget=QWidget(); widget.surface=None; widget.renderer='software'
    yield widget
    widget.close(); widget.deleteLater(); app.processEvents()


def wait_worker(startup):
    loop=QEventLoop(); timer=QTimer(); timer.setSingleShot(True)
    startup.ready.connect(loop.quit); timer.timeout.connect(loop.quit)
    timer.start(3000); loop.exec(); timer.stop()
    assert startup.finished


def test_native_abi_and_invalid_surface():
    from native_graphics import load_library
    library=load_library()
    assert library.cadence_native_abi()==1
    assert library.cadence_prepare_graphics(None)==1


def test_missing_module_keeps_software(viewer,monkeypatch,caplog):
    import native_graphics
    def missing(): raise OSError('test missing DLL')
    monkeypatch.setattr(native_graphics,'load_library',missing)
    startup=video_surface.GraphicsStartup(viewer);startup.begin();wait_worker(startup)
    assert viewer.surface is None and viewer.renderer=='software'
    assert 'test missing DLL' in caplog.text
    startup.shutdown()


def test_close_during_native_work_waits_safely(viewer,monkeypatch):
    import native_graphics
    class Library:
        def cadence_prepare_graphics(self,pointer):
            time.sleep(.15);return 3
    monkeypatch.setattr(native_graphics,'load_library',lambda:Library())
    startup=video_surface.GraphicsStartup(viewer);startup.begin();startup.shutdown()
    QApplication.processEvents()
    assert startup.closed and not startup.worker.isRunning() and startup.offscreen is None
    assert viewer.surface is None


def test_software_preference_never_starts_native_work(viewer,monkeypatch):
    video_surface.attach_surface(viewer)
    assert viewer.graphics_startup is None and viewer.renderer=='software'


def test_activation_waits_for_current_gesture(viewer,monkeypatch):
    from PySide6.QtCore import Qt
    startup=video_surface.GraphicsStartup(viewer);startup.pending=True
    monkeypatch.setattr(QApplication,'mouseButtons',lambda:Qt.MouseButton.LeftButton)
    startup.activate()
    assert startup.pending and startup.activation.isActive() and viewer.surface is None
    startup.shutdown()
