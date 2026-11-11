# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QObject,QEvent
from PySide6.QtWidgets import QApplication,QProxyStyle,QStyle,QToolTip

class TooltipFilter(QObject):
    enabled=True
    def eventFilter(self,watched,event):
        return not self.enabled and event.type()==QEvent.Type.ToolTip

def set_tooltips_enabled(enabled):
    app=QApplication.instance()
    if not hasattr(app,'cadence_tooltips'):
        app.cadence_tooltips=TooltipFilter(app); app.installEventFilter(app.cadence_tooltips)
    app.cadence_tooltips.enabled=bool(enabled)
    if not enabled: QToolTip.hideText()

class CadenceStyle(QProxyStyle):
    def __init__(self): super().__init__('Fusion')
    def styleHint(self,hint,option=None,widget=None,returnData=None):
        if hint==QStyle.StyleHint.SH_ToolTip_WakeUpDelay: return 1200
        if hint==QStyle.StyleHint.SH_ToolTip_FallAsleepDelay: return 0
        if hint==QStyle.StyleHint.SH_UnderlineShortcut: return 1
        return super().styleHint(hint,option,widget,returnData)

def install_tooltip_delay():
    app=QApplication.instance()
    if app.style().styleHint(QStyle.StyleHint.SH_ToolTip_WakeUpDelay)!=1200:
        app.setStyle(CadenceStyle())
