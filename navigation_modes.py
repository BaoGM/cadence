# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtGui import QAction,QKeySequence
from ui_text import tr


def install(window):
    for key,callback,shortcut in (
        ('Comparaison/Mode de comparaison suivant',window.cycle_comparison,'Shift+X'),
        ('Lecture/Basculer le pas clé / image',lambda:toggle_step(window),'K'),
    ):
        action=QAction(tr(key.split('/',1)[1]),window)
        action.triggered.connect(callback); action.setShortcut(QKeySequence(shortcut))
        action.setAutoRepeat(False); window.addAction(action)
        window.action_registry[key]=(action,shortcut)
    set_key_step(window,False)


def set_key_step(window,enabled):
    window.key_step=bool(enabled)
    for button,title in (
        (window.previous_key_btn,'Image précédente' if enabled else 'Clé précédente'),
        (window.next_key_btn,'Image suivante' if enabled else 'Clé suivante'),
    ):
        button.setToolTip(tr(title)); button.setAccessibleName(tr(title))


def toggle_step(window):
    if window.editing_text(): return
    set_key_step(window,not window.key_step)
    window.playback_prefs_timer.start()
