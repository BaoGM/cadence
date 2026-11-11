# SPDX-License-Identifier: GPL-3.0-only
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from test_drawing import application,window
from comparison import compose

def test_comparison_exact_pixels():
    rng=np.random.default_rng(12);a=rng.integers(0,256,(130,161,3),dtype=np.uint8);b=rng.integers(0,256,a.shape,dtype=np.uint8)
    for opacity in (0,.01,.41,.5,.99,1):
        expected=np.clip(np.rint(a.astype(np.float32)*(1-opacity)+b.astype(np.float32)*opacity),0,255).astype(np.uint8)
        assert np.array_equal(compose(a,b,'overlay',opacity),expected)
    for gain in (1,1.3,4.5,20):
        expected=np.clip(np.abs(a.astype(np.int16)-b.astype(np.int16))*gain,0,255).astype(np.uint8)
        assert np.array_equal(compose(a,b,'difference',gain=gain),expected)

def test_unchanged_effects_not_recomputed(window,monkeypatch):
    monkeypatch.setenv('CADENCE_NATIVE_RENDER','0')
    import comparison
    v=window.viewer;calls=[];original=comparison.compose
    def counted(*args): calls.append(1);return original(*args)
    monkeypatch.setattr(comparison,'compose',counted)
    v.comparing=True;v.reference_rgb=v.rgb.copy();v.compare_mode='difference';v.apply_effect()
    for _ in range(5): window.refresh();window.clip_tools.sync();v.set_exposure(v.ev)
    assert len(calls)==1
    v.compare_gain=2;v.apply_effect();assert len(calls)==2
    v.set_frame(v.rgb.copy());assert len(calls)==3

def test_welcome_opens_with_every_drawing_tool(window,application):
    w=window;opened=[];w.viewer.openRequested.disconnect();w.viewer.openRequested.connect(lambda:opened.append(1))
    for tool in w.drawing.tool_buttons:
        w.drawing.choose_tool(tool);w.viewer.clear();QTest.mouseDClick(w.viewer,Qt.MouseButton.LeftButton)
    assert len(opened)==len(w.drawing.tool_buttons)
    w.clip_tools.mode='crop';w.viewer.clear();QTest.mouseDClick(w.viewer,Qt.MouseButton.LeftButton);w.clip_tools.mode=None
    assert len(opened)==len(w.drawing.tool_buttons)+1
