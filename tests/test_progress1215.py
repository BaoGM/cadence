# SPDX-License-Identifier: GPL-3.0-only
import logging,time,threading
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QProgressDialog
from test_drawing import application,window
from progress_values import FFmpegProgress,bounded_progress
from media import run_ffmpeg,Cancelled


def test_ffmpeg_missing_negative_regressing_and_extreme_times(caplog):
 caplog.set_level(logging.INFO)
 tracker=FFmpegProgress(3.75)
 raw=['N/A',str(-(2**63)),str(-(2**63)+1),'-1000','0','1000000','500000','3750000','999999999999999999999999999999999']
 values=[tracker.update(x) for x in raw]
 assert values==[0,0,0,0,0,1/3.75,1/3.75,.99,.99]
 assert 'out_time_us=' in caplog.text and 'type=' in caplog.text

@pytest.mark.parametrize('duration',[0,-1,float('nan'),float('inf'),None])
def test_unknown_duration_stays_at_start(duration):
 assert FFmpegProgress(duration).update('1000000')==0


def test_qt_progress_is_safe_and_monotonic(window,caplog):
 caplog.set_level(logging.INFO);d=QProgressDialog(window);d.setRange(0,100);d.setAutoReset(False);d.setAutoClose(False);window.dialog=d;window._task_progress_value=0.
 try:
  raw=[min(.99,(-9223372036854775807)/1e6/3.75)*.8,float('nan'),float('-inf'),0.,.5,.1,float('inf'),10**400,1.,2.]
  seen=[]
  for p in raw: window.task_progress(p,'Test');seen.append(d.value())
  assert seen==[0,0,0,0,50,50,50,50,100,100]
  assert 'percent_type=int' in caplog.text and 'normalized=' in caplog.text
 finally: window.dialog=None;d.close();d.deleteLater()


def test_real_ffmpeg_success_failure_and_cancel(tmp_path):
 values=[]
 run_ffmpeg(['-stats_period','0.01','-f','lavfi','-i','testsrc2=size=320x180:rate=24:duration=1','-c:v','libx264',str(tmp_path/'test.avi')],lambda p,m:values.append(p),duration=1)
 assert values[-1]==1 and values==sorted(values) and all(0<=p<=1 for p in values)
 values=[]
 with pytest.raises(RuntimeError):run_ffmpeg(['-i',str(tmp_path/'missing.avi'),str(tmp_path/'bad.mp4')],lambda p,m:values.append(p),duration=1)
 assert 1 not in values
 cancel=threading.Event();cancel.set()
 with pytest.raises(Cancelled):run_ffmpeg(['-f','lavfi','-i','color=red:s=64x64:d=1',str(tmp_path/'cancel.mp4')],cancel=cancel,duration=1)


def test_modal_completion_can_clear_dialog(window,application):
 from PySide6.QtCore import QTimer
 d=QProgressDialog(window);d.setRange(0,100);d.setAutoReset(False);d.setWindowModality(Qt.WindowModality.WindowModal);window.dialog=d;window._task_progress_value=0.;d.show()
 QTimer.singleShot(0,lambda:setattr(window,'dialog',None))
 window.task_progress(.5,'Test');application.processEvents();assert window.dialog is None
 window.task_progress(1,'Terminé');d.close();d.deleteLater()
