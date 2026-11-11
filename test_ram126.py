# SPDX-License-Identifier: GPL-3.0-only
import numpy as np
from cache_ram import FrameCache,MIB,default_cache_mb,maximum_cache_mb
from preferences import defaults,validate
from test_drawing import application,window

def test_cache_eviction_and_live_limit():
    cache=FrameCache(24); a=np.zeros(12,dtype=np.uint8)
    cache.put('a',a); cache.put('b',a.copy()); assert cache.get('a') is a
    cache.put('c',a.copy()); assert cache.get('b') is None and cache.bytes==24
    cache.set_budget(12); assert cache.get('a') is None and cache.get('c') is not None
    cache.put('huge',np.zeros(30,dtype=np.uint8)); assert cache.bytes==12
    cache.clear(); assert cache.bytes==0 and not cache.frames

def test_ram_preferences_and_shared_cache(window):
    from preferences import ShortcutDialog
    w=window
    assert w.decoder.cache is w.reference_decoder.cache is w.frame_cache
    assert w.preferences['ram_cache_mb']==default_cache_mb()
    data=dict(w.preferences,ram_cache_mb=256); w.apply_preferences(data)
    assert w.frame_cache.budget==256*MIB
    assert validate(dict(data,ram_cache_mb=10**12),w.action_registry)['ram_cache_mb']==maximum_cache_mb()
    dialog=ShortcutDialog(w.action_registry,data,w)
    assert dialog.ram_cache.value()==256
    dialog.ram_cache.setValue(512); assert dialog.collect()['ram_cache_mb']==512
    assert dialog.general_preferences()['ram_cache_mb']==512
    dialog.deleteLater()

def test_numeric_fields_remain_visible_without_step_buttons(window,application):
    from PySide6.QtWidgets import QAbstractSpinBox,QStyleOptionSpinBox,QStyle
    from app import STYLE
    application.setStyleSheet(STYLE)
    from preferences import ShortcutDialog
    dialog=ShortcutDialog(window.action_registry,window.preferences,window);dialog.show();application.processEvents()
    for root in (window,dialog):
        for spin in root.findChildren(QAbstractSpinBox):
            if not spin.isVisible():continue
            assert spin.lineEdit().width()>30
            option=QStyleOptionSpinBox();spin.initStyleOption(option)
            for part in (QStyle.SubControl.SC_SpinBoxUp,QStyle.SubControl.SC_SpinBoxDown):
                assert spin.style().subControlRect(QStyle.ComplexControl.CC_SpinBox,option,part,spin).width()==0
    dialog.reject();dialog.deleteLater()
