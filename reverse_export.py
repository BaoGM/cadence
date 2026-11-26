# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
import tempfile
import uuid

from cadence_change import video_filter
from model import with_tracks


MEMORY_LIMIT = 64 * 1024 * 1024


def reverse_packets(forward, destination, fps, length, cancel):
    import av
    from media import Cancelled
    from media_inputs import open_local_media

    # FFV1 was encoded as independent frames. Reverse compressed packets on disk
    # so the working set does not grow with the duration of a shot.
    clock = 1 / Fraction(fps)
    with tempfile.TemporaryFile(dir=destination.parent) as spool, av.open(str(destination), 'w') as output:
        count = 0
        with open_local_media(str(forward)) as source:
            stream = source.streams.video[0]
            target = output.add_stream_from_template(stream)
            for packet in source.demux(stream):
                if cancel and cancel.is_set():
                    raise Cancelled()
                if packet.size == 0:
                    continue
                if not packet.is_keyframe:
                    raise ValueError('Image intermédiaire invalide.')
                spool.write(memoryview(packet))
                spool.write(packet.size.to_bytes(8, 'little'))
                count += 1
        if count != length:
            raise ValueError('La durée du média a changé.')
        forward.unlink()
        position = spool.tell()
        for index in range(count):
            if cancel and cancel.is_set():
                raise Cancelled()
            spool.seek(position - 8)
            size = int.from_bytes(spool.read(8), 'little')
            position -= 8 + size
            spool.seek(position)
            packet = av.Packet(spool.read(size))
            packet.stream = target
            packet.time_base = clock
            packet.pts = packet.dts = index
            packet.duration = 1
            packet.is_keyframe = True
            output.mux(packet)


def prepare_reversed_video(state, media, sources, fps, folder, progress, cancel):
    from media import run_ffmpeg

    converted = {}
    output_media = dict(media)
    tracks = []
    for track in state.tracks:
        segments = []
        for clip in track.segments:
            if not clip.reversed or clip.muted or clip.media not in sources:
                segments.append(clip)
                continue
            source = media[clip.media]
            span = (clip.media,clip.start,clip.end)
            if span not in converted:
                identity = uuid.uuid4().hex
                destination = Path(folder) / (identity + '.nut')
                filters = video_filter(fps,source.get('cadence')) + f',trim=start_frame={clip.start}:end_frame={clip.end}'
                small = clip.length * source['width'] * source['height'] * 8 <= MEMORY_LIMIT
                temporary = destination if small else destination.with_suffix('.forward.nut')
                if small:
                    filters += ',reverse'
                run_ffmpeg(['-i',source['path'],'-map','0:v:0','-an','-vf',filters+',setpts=PTS-STARTPTS',
                            '-c:v','ffv1','-g','1','-level','3',str(temporary)],
                           lambda p,m:progress(.1,'Inverser le média'),cancel,float(clip.length/fps))
                if not small:
                    reverse_packets(temporary,destination,fps,clip.length,cancel)
                converted[span] = identity
                output_media[identity] = dict(source,id=identity,path=str(destination),cadence=None,frames=clip.length)
            segments.append(replace(clip,media=converted[span],start=0,end=clip.length,reversed=False))
        tracks.append(replace(track,segments=tuple(segments),audio_segments=track.audio))
    state = with_tracks(state,tracks)
    sources = list(dict.fromkeys(clip.media for track in tracks for clip in track.segments
                                 if not clip.muted and (clip.media in sources or clip.media in converted.values())))
    return state,output_media,sources
