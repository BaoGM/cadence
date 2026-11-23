# SPDX-License-Identifier: GPL-3.0-only
from collections import OrderedDict
from fractions import Fraction

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot, Qt
from PySide6.QtGui import QImage, QTransform


class ThumbnailResult(QObject):
    ready = Signal(object, object)


class ReadThumbnails(QRunnable):
    def __init__(self, key, result):
        super().__init__()
        self.key = key
        self.result = result

    def run(self):
        import av
        path, _, _, rotation, start, end, fps, offset, samples = self.key
        images = []
        try:
            with av.open(path, timeout=(3, 3)) as movie:
                video = movie.streams.video[0]
                video.codec_context.thread_count = 1
                for index in range(samples):
                    seconds = offset + (start + (end - start - 1) * Fraction(index, samples)) / fps
                    try:
                        target = int(seconds / video.time_base)
                        movie.seek(target, stream=video)
                        decoded = movie.decode(video)
                        frame = next(decoded)
                        # On inter-frame codecs the seek lands on the preceding keyframe.
                        # Advance to the cut itself, with a bounded fallback on an unusually long GOP.
                        for _ in range(96):
                            if frame.pts is None or frame.pts >= target: break
                            following = next(decoded, None)
                            if following is None: break
                            frame = following
                    except (StopIteration, av.FFmpegError):
                        break
                    w, h = frame.width, frame.height
                    scale = 96 / max(w, h)
                    rgb = frame.reformat(width=max(1, round(w * scale)), height=max(1, round(h * scale)), format='rgb24')
                    plane = rgb.planes[0]
                    image = QImage(bytes(plane), rgb.width, rgb.height, plane.line_size, QImage.Format.Format_RGB888).copy()
                    if rotation:
                        image = image.transformed(QTransform().rotate(-rotation))
                    images.append(image)
        except (OSError, ValueError, IndexError, av.FFmpegError):
            pass
        try:
            self.result.ready.emit(self.key, tuple(images))
        except RuntimeError:
            pass


class ClipThumbnails(QObject):
    def __init__(self, timeline):
        super().__init__(timeline)
        self.result = ThumbnailResult(self)
        self.result.ready.connect(self.complete, Qt.ConnectionType.QueuedConnection)
        self.cache = OrderedDict()
        self.pending = set()

    def get(self, media, segment, strip=False):
        path = media.get('proxy')
        if not path or not media.get('has_video', True):
            return ()
        fps = Fraction(str(media.get('fps') or 24))
        key = (str(path), media.get('size'), media.get('mtime_ns'), media.get('preview_rotation', 0),
               segment.start, segment.end, fps, Fraction(str(media.get('direct_start') or 0)))
        full, first = (*key, 7), (*key, 1)
        if full in self.cache:
            self.cache.move_to_end(full)
            return self.cache[full] or self.cache.get(first, ())
        preview = self.cache.get(first, ())
        if first in self.cache:
            self.cache.move_to_end(first)
            if not strip or not preview:
                return preview
        key = full if preview else first
        # Schedule only visible clips and limit concurrent I/O when scrubbing a long cut.
        if key not in self.pending and len(self.pending) < 2:
            self.pending.add(key)
            QThreadPool.globalInstance().start(ReadThumbnails(key, self.result), -1)
        return preview

    @Slot(object, object)
    def complete(self, key, images):
        self.pending.discard(key)
        self.cache[key] = images
        if len(self.cache) > 256:
            self.cache.popitem(last=False)
        self.parent().update()
