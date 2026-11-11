// SPDX-License-Identifier: GPL-3.0-only
#include <QtCore/QtGlobal>
#include <QtCore/QElapsedTimer>
#include <QtCore/QThread>
#include <QtGui/QOffscreenSurface>
#include <QtGui/QOpenGLContext>
#include <QtGui/QSurfaceFormat>

#define CADENCE_API extern "C" Q_DECL_EXPORT

CADENCE_API int cadence_native_abi() noexcept { return 1; }
CADENCE_API const char* cadence_native_qt() noexcept { return QT_VERSION_STR; }

static thread_local double phase_seconds[3] = {};
CADENCE_API void cadence_graphics_timings(double* values) noexcept
{
    if (values) for (int i = 0; i < 3; ++i) values[i] = phase_seconds[i];
}

CADENCE_API int cadence_prepare_graphics(void* surface_pointer) noexcept
{
    auto* surface = static_cast<QOffscreenSurface*>(surface_pointer);
    if (!surface || !surface->isValid()) return 1;
    // The surface is created on the GUI thread; its context stays on this worker.
    if (QThread::currentThread() == surface->thread()) return 2;
    try {
        QElapsedTimer timer;
        timer.start();
        {
            QOpenGLContext context;
            context.setFormat(surface->format());
            if (!context.create()) return 3;
            phase_seconds[0] = timer.nsecsElapsed() / 1.e9;
            timer.restart();
            if (!context.makeCurrent(surface)) return 4;
            context.doneCurrent();
            phase_seconds[1] = timer.nsecsElapsed() / 1.e9;
            timer.restart();
        }
        phase_seconds[2] = timer.nsecsElapsed() / 1.e9;
        return 0;
    } catch (...) {
        return 5;
    }
}
