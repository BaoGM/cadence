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
        from av import FFmpegError
        from media_inputs import open_local_media
        from export_sources import open_shared
        path, _, _, rotation, start, end, fps, offset, samples = self.key
        images = []
        try:
            with open_shared(path) as stream, open_local_media(stream, timeout=(3, 3), buffer_size=256*1024) as movie:
                video = movie.streams.video[0]
                video.codec_context.thread_count = 1
                for index in range(samples):
                    last = end + 1 if end < start else end - 1
                    seconds = offset + (start + (last-start) * Fraction(index, samples)) / fps
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
                    except (StopIteration, FFmpegError):
                        break
                    w, h = frame.width, frame.height
                    scale = 96 / max(w, h)
                    rgb = frame.reformat(width=max(1, round(w * scale)), height=max(1, round(h * scale)), format='rgb24')
                    plane = rgb.planes[0]
                    image = QImage(bytes(plane), rgb.width, rgb.height, plane.line_size, QImage.Format.Format_RGB888).copy()
                    if rotation:
                        image = image.transformed(QTransform().rotate(-rotation))
                    images.append(image)
        except (OSError, ValueError, IndexError, FFmpegError):
            pass
        try:
            self.result.ready.emit(self.key, tuple(images))
        except RuntimeError:
            pass


class ClipThumbnails(QObject):
    changed = Signal()

    def __init__(self, owner, repaint=True):
        super().__init__(owner)
        if repaint:
            self.changed.connect(owner.update)
        self.result = ThumbnailResult(self)
        self.result.ready.connect(self.complete, Qt.ConnectionType.QueuedConnection)
        self.cache = OrderedDict()
        self.pending = set()
        self.trim_edges = OrderedDict()

    def get(self, media, segment, strip=False, resizing=False):
        source = (segment.media, media.get('proxy'), media.get('size'), media.get('mtime_ns'),
                  media.get('preview_rotation'), media.get('fps'), media.get('direct_start'),
                  segment.reversed, segment.warp)
        edges = ((source, 'start', segment.start), (source, 'end', segment.end))
        previous = max((self.trim_edges[edge] for edge in edges if edge in self.trim_edges),
                       key=lambda entry: len(entry[1]), default=None)
        # A moving edge changes the decode key on every mouse move. Keep painting the
        # last decoded poses from the shared edge until the committed range is ready.
        moving = resizing and previous and previous[0] != segment
        images = () if moving else self.read_segment(media, segment, strip)
        ready = images and (not strip or len(images) > 1 or not previous or len(previous[1]) == 1)
        if ready or previous and not resizing:
            entry = (segment, images) if ready else previous
            for edge in edges:
                self.trim_edges[edge] = entry
                self.trim_edges.move_to_end(edge)
            while len(self.trim_edges) > 256:
                self.trim_edges.popitem(last=False)
        if ready:
            return images
        if not previous:
            return ()
        old, poses = previous
        count = 7 if strip else 1
        sampled = []
        for i in range(count):
            offset = (segment.length - 1) * i / count
            frame = segment.source_frame(offset)
            relative = old.end - 1 - frame if old.reversed else frame - old.start
            nearest = round(relative * len(poses) / max(1, old.length - 1))
            sampled.append(poses[max(0, min(len(poses) - 1, nearest))])
        if images:
            sampled[0] = images[0]
        return tuple(sampled)

    def read_segment(self, media, segment, strip):
        if segment.warp and segment.start>=segment.warp[0][0] and segment.end-1<=segment.warp[-1][0]:
            from dataclasses import replace
            from time_warp import render_info
            media=render_info(media,segment.warp)
            shift=segment.warp[0][0]
            segment=replace(segment,start=segment.start-shift,end=segment.end-shift,warp=())
        elif segment.warp:
            from time_warp import video_sample
            count=min(7,segment.length) if strip else 1
            images=[]
            for i in range(count):
                sample=segment.source_frame(i*(segment.length-1)//max(1,count-1))
                source,index=video_sample(media,segment,sample)
                result=self.request((str(source['proxy']),source.get('size'),source.get('mtime_ns'),
                                     source.get('preview_rotation',0),index,index+1,Fraction(source['fps']),
                                     Fraction(str(source.get('direct_start') or 0))),False)
                images.append(result[0] if result else None)
            if None in images:
                return (images[0],) if images[0] is not None else ()
            return tuple(images)
        path = media.get('proxy')
        if not path or not media.get('has_video', True):
            return ()
        fps = Fraction(str(media.get('fps') or 24))
        key = (str(path), media.get('size'), media.get('mtime_ns'), media.get('preview_rotation', 0),
               segment.source_frame(0), segment.source_frame(segment.length), fps, Fraction(str(media.get('direct_start') or 0)))
        return self.request(key,strip)

    def request(self,key,strip=False):
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
        self.changed.emit()
