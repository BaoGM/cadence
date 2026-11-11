// SPDX-License-Identifier: GPL-3.0-only
#include <QtCore/QtGlobal>
#include <QtGui/QPainter>
#include <algorithm>
#include <array>
#include <atomic>
#include <thread>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>

#define CADENCE_API extern "C" Q_DECL_EXPORT

CADENCE_API int cadence_render_abi() noexcept { return 1; }

CADENCE_API int cadence_alpha_bounds(const void* image_pointer, int* bounds) noexcept
{
    const auto* image = static_cast<const QImage*>(image_pointer);
    if (!image || !bounds || image->format() != QImage::Format_ARGB32_Premultiplied) return 1;
    int left = image->width(), right = -1, top = image->height(), bottom = -1;
    for (int y = 0; y < image->height(); ++y) {
        const auto* row = reinterpret_cast<const QRgb*>(image->constScanLine(y));
        int first = 0, last = image->width() - 1;
        while (first <= last && !qAlpha(row[first])) ++first;
        if (first > last) continue;
        while (!qAlpha(row[last])) --last;
        left = std::min(left, first); right = std::max(right, last);
        top = std::min(top, y); bottom = y;
    }
    bounds[0] = right < 0 ? 0 : left; bounds[1] = bottom < 0 ? 0 : top;
    bounds[2] = right < 0 ? 0 : right - left + 1; bounds[3] = bottom < 0 ? 0 : bottom - top + 1;
    return 0;
}

static void rgb_rows(const uint8_t* a, ptrdiff_t a_row, ptrdiff_t a_pixel,
    const uint8_t* b, ptrdiff_t b_row, ptrdiff_t b_pixel,
    uint8_t* output, ptrdiff_t output_row, int width, const uint8_t* table, int begin, int end) noexcept
{
    for (int y = begin; y < end; ++y) {
        const auto* aa = a + y * a_row;
        const auto* bb = b ? b + y * b_row : nullptr;
        auto* dst = output + y * output_row;
        if (bb) {
            for (int x = 0; x < width; ++x, aa += a_pixel, bb += b_pixel, dst += 3) {
                dst[0] = table[(unsigned(aa[0]) << 8) | bb[0]];
                dst[1] = table[(unsigned(aa[1]) << 8) | bb[1]];
                dst[2] = table[(unsigned(aa[2]) << 8) | bb[2]];
            }
        } else {
            for (int x = 0; x < width; ++x, aa += a_pixel, dst += 3) {
                dst[0] = table[aa[0]];
                dst[1] = table[aa[1]];
                dst[2] = table[aa[2]];
            }
        }
    }
}

CADENCE_API int cadence_rgb_lut(
    const uint8_t* a, ptrdiff_t a_row, ptrdiff_t a_pixel,
    const uint8_t* b, ptrdiff_t b_row, ptrdiff_t b_pixel,
    uint8_t* output, ptrdiff_t output_row, int width, int height,
    const uint8_t* table) noexcept
{
    if (!a || !output || !table || width <= 0 || height <= 0 ||
        width > std::numeric_limits<int>::max() / 3 || output_row < width * 3)
        return 1;
    auto rows = [=](int begin, int end) { rgb_rows(a,a_row,a_pixel,b,b_row,b_pixel,output,output_row,width,table,begin,end); };
    if (size_t(width) * height < 1048576) { rows(0, height); return 0; }
    // Bound extra workers across concurrent preview/export calls; join before returning any borrowed buffer.
    static std::atomic<int> available{3};
    int count = 0;
    for (; count < 3; ++count) {
        int value = available.load(std::memory_order_relaxed);
        while (value > 0 && !available.compare_exchange_weak(value, value - 1, std::memory_order_relaxed)) {}
        if (value <= 0) break;
    }
    std::array<std::thread, 3> workers;
    const int pieces = count + 1;
    for (int i = 0; i < count; ++i) {
        const int begin = int(int64_t(height) * i / pieces);
        const int end = int(int64_t(height) * (i + 1) / pieces);
        try { workers[i] = std::thread([&, begin, end] { rows(begin, end); }); }
        catch (...) { rows(begin, end); }
    }
    rows(int(int64_t(height) * count / pieces), height);
    for (int i = 0; i < count; ++i) if (workers[i].joinable()) workers[i].join();
    available.fetch_add(count, std::memory_order_relaxed);
    return 0;
}

CADENCE_API int cadence_paint_stroke(void* painter_pointer, const double* points,
    size_t count, int width, int height, double size, int pressure, double sensitivity) noexcept
{
    auto* painter = static_cast<QPainter*>(painter_pointer);
    if (!painter || !painter->isActive() || !points || !count ||
        width <= 0 || height <= 0 || width > 65536 || height > 65536 ||
        !std::isfinite(size) || size <= 0 || size > 2 ||
        !std::isfinite(sensitivity) || sensitivity < .1 || sensitivity > 5 || count > 10000000)
        return 1;
    for (size_t i = 0; i < count; ++i) {
        const double x = points[i * 3], y = points[i * 3 + 1], p = points[i * 3 + 2];
        if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(p) ||
            x < -4 || x > 5 || y < -4 || y > 5 || p < 0 || p > 1) return 1;
    }
    auto radius = [&](double p) {
        const double factor = pressure ? std::max(.03, std::pow(std::clamp(p, 0., 1.), sensitivity)) : 1.;
        return std::max(.35, size * height * factor / 2);
    };
    try {
        double x0 = points[0], y0 = points[1], r0 = radius(points[2]);
        painter->drawEllipse(QPointF(x0 * width, y0 * height), r0, r0);
        for (size_t i = 1; i < count; ++i) {
            const double x = points[i * 3], y = points[i * 3 + 1], r = radius(points[i * 3 + 2]);
            const double distance = std::hypot((x - x0) * width, (y - y0) * height);
            const double steps = std::max(1., std::ceil(distance / std::max(.5, std::min(r, r0) * .4)));
            for (double j = 1.; j <= steps; ++j) {
                const double t = j / steps, rr = r0 + (r - r0) * t;
                painter->drawEllipse(QPointF((x0 + (x - x0) * t) * width, (y0 + (y - y0) * t) * height), rr, rr);
            }
            x0 = x; y0 = y; r0 = r;
        }
        return 0;
    } catch (...) {
        return 2;
    }
}
