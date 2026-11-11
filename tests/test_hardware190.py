# SPDX-License-Identifier: GPL-3.0-only
from types import SimpleNamespace
import numpy as np
import pytest
from media import PreviewReader,DecodeSuperseded
from hardware_decode import open_preview


def test_hardware_open_failure_falls_back(monkeypatch):
    import av
    import av.codec.hwaccel
    monkeypatch.setenv('CADENCE_HW_DECODE','d3d11va')
    monkeypatch.setattr(av.codec.hwaccel,'hwdevices_available',lambda:['d3d11va'])
    calls=[]; software=object()
    def opening(path,**options):
        calls.append(options)
        if options: raise RuntimeError('device unavailable')
        return software
    monkeypatch.setattr(av,'open',opening)
    assert open_preview('test.avi')==(software,False)
    assert len(calls)==2 and not calls[-1]


def test_unsupported_codec_closes_unused_device(monkeypatch):
    import av
    import av.codec.hwaccel
    monkeypatch.setenv('CADENCE_HW_DECODE','d3d11va')
    monkeypatch.setattr(av.codec.hwaccel,'hwdevices_available',lambda:['d3d11va'])
    closed=[]; unused=SimpleNamespace(streams=SimpleNamespace(video=[SimpleNamespace(codec_context=SimpleNamespace(is_hwaccel=False))]),close=lambda:closed.append(True))
    software=object(); monkeypatch.setattr(av,'open',lambda path,**kw:unused if kw else software)
    assert open_preview('test.avi')==(software,False) and closed==[True]


def test_read_retries_same_frame_and_disables_failed_device(monkeypatch):
    reader=PreviewReader();media={'proxy':'source'};identity=('source',None,None);calls=[];closed=[]
    reader.hardware.add(identity);reader.containers[identity]=SimpleNamespace(close=lambda:closed.append(True));reader.pending[identity]=object()
    expected=np.zeros((2,2,3),np.uint8)
    def read(media,index,superseded):
        calls.append(index)
        if len(calls)==1: raise RuntimeError('device lost')
        assert identity in reader.hardware_failed and identity not in reader.pending
        return expected
    monkeypatch.setattr(reader,'_read',read)
    assert reader.read(media,125) is expected and calls==[125,125] and closed==[True]
    reader.close()


def test_cancellation_is_not_a_hardware_failure(monkeypatch):
    reader=PreviewReader();reader.hardware.add(('source',None,None))
    def read(*args): raise DecodeSuperseded()
    monkeypatch.setattr(reader,'_read',read)
    with pytest.raises(DecodeSuperseded):reader.read({'proxy':'source'},10)
    assert not reader.hardware_failed
    reader.close()
