# SPDX-License-Identifier: GPL-3.0-only
from html import escape
from pathlib import Path
import sys
from ui_text import language,tr

def shortcut_lines(registry,layout='QWERTY'):
    from PySide6.QtGui import QKeySequence
    from menu_layout import alphabetical
    french=language()=='fr'
    title='Raccourcis actifs' if french else 'Active shortcuts'
    lines=[f'{title} ({layout})']
    categories={}
    for path,(action,_) in registry.items():
        if action.shortcuts():
            categories.setdefault(path.split('/',1)[0],[]).append(action)
    for category,actions in categories.items():
        lines+=['',tr(category)]
        for action in sorted(actions,key=lambda a:alphabetical(a.text())):
            bindings=[]
            for sequence in action.shortcuts():
                keys=sequence.toString(QKeySequence.SequenceFormat.NativeText)
                if keys==',': keys='Virgule' if french else 'Comma'
                elif keys=='.': keys='Point' if french else 'Period'
                bindings.append(keys)
            lines.append(' / '.join(bindings)+(' : ' if french else ': ')+action.text())
    return '\n'.join(lines)

def guide_text(registry,layout='QWERTY'):
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'assets'
    return (root/('guide_'+language()+'.txt')).read_text(encoding='utf-8')+'\n\n'+'-'*40+'\n\n'+shortcut_lines(registry,layout)+'\n'

def fill_browser(browser,registry,layout='QWERTY'):
    text=guide_text(registry,layout)
    browser.setStyleSheet("QTextBrowser {font-family:'Noto Sans';font-size:13px;padding:12px;}")
    parts=[]
    for index,paragraph in enumerate(text.strip().split('\n\n')):
        lines=paragraph.strip().splitlines()
        if not lines: continue
        if lines[0]=='-'*40:
            parts.append('<hr color="#354354">'); lines.pop(0)
            if not lines: continue
        heading=index==0 or (len(lines[0])<65 and not any(mark in lines[0] for mark in (':',' - ','%','/','.')))
        if heading: parts.append('<h2>'+escape(lines.pop(0))+'</h2>')
        if lines: parts.append('<p>'+'<br>'.join(escape(line) for line in lines)+'</p>')
    browser.document().setDefaultStyleSheet('h2 {font-size:14px;font-weight:600;margin-top:12px;margin-bottom:8px;} p {margin-top:4px;margin-bottom:10px;}')
    browser.setHtml(''.join(parts))
