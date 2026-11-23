# SPDX-License-Identifier: GPL-3.0-only
from fractions import Fraction


class TimestampPreview:
    def __init__(self, container, origin, fps):
        self.container = container
        self.stream = container.streams.video[0]
        self.origin = Fraction(origin)
        self.fps = Fraction(fps)
        self.decoder = None
        self.current = None
        self.pending = None
        self.last_request = None
        self.eof = False

    def position(self, frame):
        # Match FFmpeg's fps=...:round=near, including exact half-frame ties.
        value = (Fraction(frame.pts) * frame.time_base - self.origin) * self.fps
        return (2 * value.numerator + value.denominator) // (2 * value.denominator)

    def seek(self, index, preroll=0):
        target = self.origin + Fraction(index, 1) / self.fps - preroll
        self.container.seek(int(target / self.stream.time_base), stream=self.stream, backward=True)
        self.decoder = self.container.decode(video=0)
        self.current = None
        self.pending = None
        self.eof = False

    def read(self, index, superseded=None):
        from media import DecodeSuperseded
        if self.decoder is None or self.last_request is None or not self.last_request <= index <= self.last_request + 32:
            self.seek(index)
        self.last_request = index
        retried = False
        while True:
            if superseded is not None and superseded():
                raise DecodeSuperseded()
            if self.pending is None and not self.eof:
                try:
                    self.pending = next(self.decoder)
                except StopIteration:
                    self.eof = True
            if self.pending is None:
                if self.current is None:
                    raise RuntimeError(f'Image {index} indisponible.')
                return self.current
            if self.pending.pts is None:
                raise RuntimeError('Horodatage vidéo absent pendant la lecture.')
            position = self.position(self.pending)
            if position > index:
                if self.current is not None:
                    return self.current
                if not retried:
                    # A seek can land on a keyframe whose rounded timestamp is too late.
                    self.seek(index, max(Fraction(1), Fraction(index, 1) / self.fps))
                    retried = True
                    continue
                raise RuntimeError(f'Horodatage vidéo introuvable pour l’image {index}.')
            if self.current is not None and self.pending.pts * self.pending.time_base < self.current.pts * self.current.time_base:
                raise RuntimeError('Horodatages vidéo non ordonnés pendant la lecture.')
            self.current, self.pending = self.pending, None
