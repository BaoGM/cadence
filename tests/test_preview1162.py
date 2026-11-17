# SPDX-License-Identifier: GPL-3.0-only
from fractions import Fraction
from pathlib import Path
import random
import threading

import av
import numpy as np
import pytest

import media
from test_drawing import application, window


@pytest.fixture
def clip(tmp_path, monkeypatch):
    monkeypatch.setenv('CADENCE_CACHE', str(tmp_path / 'cache'))
    path = tmp_path / 'variable.mp4'
    media.run_ffmpeg(['-f', 'lavfi', '-i', 'testsrc2=s=160x96:r=24:d=4',
                     '-vf', "select='not(eq(mod(n,7),3))'", '-fps_mode', 'vfr',
                     '-c:v', 'libx264', '-crf', '0', '-g', '24', '-bf', '3', str(path)])
    return path


def reference(path, fps, directory):
    target = directory / 'reference.rgb'
    media.run_ffmpeg(['-i', str(path), '-vf', f'setpts=PTS-STARTPTS,fps={fps},setsar=1',
                     '-an', '-pix_fmt', 'rgb24', '-f', 'rawvideo', str(target)])
    with av.open(str(path)) as container:
        frame = next(container.decode(video=0))
        width, height = frame.width, frame.height
        if getattr(frame, 'rotation', 0) % 180:
            width, height = height, width
    return np.fromfile(target, dtype=np.uint8).reshape(-1, height, width, 3)


@pytest.mark.parametrize('fps', [None, Fraction(24), Fraction(30000, 1001), Fraction(12)])
def test_vfr_immediate_import_and_seek_match_ffmpeg(clip, tmp_path, monkeypatch, fps):
    def forbid_conversion(*args, **kwargs):
        pytest.fail('Opening this file must not launch a full video conversion')
    with monkeypatch.context() as local:
        local.setattr(media, 'run_ffmpeg', forbid_conversion)
        item = media.prepare_media(clip, fps, defer_audio=True)
    assert item['direct_timestamps'] and item['proxy'] == str(clip)
    assert not list((tmp_path / 'cache').rglob('preview.avi'))
    expected = reference(clip, item['fps'], tmp_path)
    assert item['frames'] == len(expected)
    reader = media.PreviewReader(budget=1, retain_decoded=True)
    indices = list(range(len(expected)))
    random.Random(1162).shuffle(indices)
    try:
        for index in [0, len(expected)-1, *indices, *range(len(expected)), *reversed(range(len(expected)))]:
            np.testing.assert_array_equal(reader.read(item, index), expected[index], err_msg=f'frame {index}')
    finally:
        reader.close()


@pytest.mark.parametrize('bframes,offset', [(0, 0), (3, 0), (3, 2)])
def test_unknown_frame_count_fragmented_mp4(tmp_path, monkeypatch, bframes, offset):
    monkeypatch.setenv('CADENCE_CACHE', str(tmp_path / 'cache'))
    path = tmp_path / 'fragmented.mp4'
    media.run_ffmpeg(['-f', 'lavfi', '-i', 'testsrc2=s=160x96:r=24:d=3',
                     '-c:v', 'libx264', '-bf', str(bframes), '-g', '24',
                     '-output_ts_offset', str(offset), '-movflags', '+frag_keyframe+empty_moov', str(path)])
    assert media.probe(path)['frames'] == 0
    item = media.prepare_media(path, defer_audio=True)
    assert item['direct_timestamps']
    expected = reference(path, item['fps'], tmp_path)
    assert item['frames'] == len(expected) == 72
    reader = media.PreviewReader(budget=1)
    try:
        for index in [0, 71, 24, 25, 2, 70]:
            np.testing.assert_array_equal(reader.read(item, index), expected[index])
    finally:
        reader.close()


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
def test_rotation_and_sar_keep_ffmpeg_pixels(tmp_path, monkeypatch, rotation):
    monkeypatch.setenv('CADENCE_CACHE', str(tmp_path / 'cache'))
    base = tmp_path / 'base.mp4'
    path = tmp_path / 'rotated.mp4'
    media.run_ffmpeg(['-f', 'lavfi', '-i', 'testsrc2=s=160x96:r=24:d=1',
                     '-vf', 'setsar=4/3', '-c:v', 'libx264', '-crf', '0', str(base)])
    media.run_ffmpeg(['-i', str(base), '-c', 'copy', '-metadata:s:v:0', f'rotate={rotation}', str(path)])
    item = media.prepare_media(path, defer_audio=True)
    assert item['proxy'] == str(path)
    expected = reference(path, item['fps'], tmp_path)
    reader = media.PreviewReader(budget=1)
    try:
        for index in [0, 23, 12]:
            np.testing.assert_array_equal(reader.read(item, index), expected[index])
    finally:
        reader.close()


def test_timestamp_cancellation_then_new_request(clip):
    item = media.prepare_media(clip, Fraction(24), defer_audio=True)
    reader = media.PreviewReader(budget=1)
    checks = []
    def superseded():
        checks.append(True)
        return len(checks) > 4
    try:
        with pytest.raises(media.DecodeSuperseded):
            reader.read(item, 18, superseded)
        expected = media.PreviewReader(budget=1)
        try:
            for index in [19, 1, 95, 3]:
                np.testing.assert_array_equal(reader.read(item, index), expected.read(item, index))
        finally:
            expected.close()
    finally:
        reader.close()


def test_preparation_cancelled_before_conversion(clip):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(media.Cancelled):
        media.prepare_media(clip, cancel=cancel, defer_audio=True)


def test_timestamp_rates_do_not_share_wrong_cached_frames(clip):
    items = [media.prepare_media(clip, Fraction(fps), defer_audio=True) for fps in (12, 24)]
    reader = media.PreviewReader()
    fresh = media.PreviewReader(budget=1)
    try:
        for index, item in [(12, items[0]), (12, items[1]), (15, items[0]), (13, items[1]), (1, items[0])]:
            np.testing.assert_array_equal(reader.read(item, index), fresh.read(item, index))
    finally:
        reader.close()
        fresh.close()


def test_pending_audio_and_cached_reopen(clip):
    from audio_prepare import prepare_audio
    path = clip.with_name('audio.mp4')
    media.run_ffmpeg(['-i', str(clip), '-f', 'lavfi', '-i', 'sine=frequency=440:duration=4',
                     '-c:v', 'copy', '-c:a', 'aac', '-shortest', str(path)])
    item = media.prepare_media(path, defer_audio=True)
    assert item['audio_pending'] and item['direct_timestamps']
    completed = prepare_audio(item)
    assert not completed['audio_pending']
    assert np.max(np.load(completed['waveform'])) > 0
    cached = media.prepare_media(path, defer_audio=True)
    assert cached == completed
    assert Path(cached['audio']).stat().st_size == media.sample_at(cached['frames'], Fraction(cached['fps'])) * 4


def test_timestamp_preview_through_window(window, tmp_path, monkeypatch):
    from smoke import check_timestamp_preview
    monkeypatch.setenv('CADENCE_CACHE', str(tmp_path / 'cache'))
    assert check_timestamp_preview(window, tmp_path)['timestamp_preview']
