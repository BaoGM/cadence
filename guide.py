# SPDX-License-Identifier: GPL-3.0-only
from html import escape
from pathlib import Path
import sys
from ui_text import language,tr

def shortcut_lines(registry):
    french=language()=='fr'
    lines=['Raccourcis clavier par défaut' if french else 'Default keyboard shortcuts','']
    from menu_layout import alphabetical
    for category in ('Fichier','Édition','Lecture','Affichage','Comparaison','Dessin','Outils','Aide'):
        entries=[(action,key) for path,(action,key) in registry.items() if path.startswith(category+'/') and key]
        if not entries: continue
        lines+=['',tr(category)]
        for action,default in sorted(entries,key=lambda item:alphabetical(item[0].text())):
            keys=default
            if french:
                for a,b in [('Shift','Maj'),('Delete','Suppr'),('Space','Espace'),('Escape','Échap'),('Left','Gauche'),('Right','Droite'),('Home','Début'),('End','Fin')]: keys=keys.replace(a,b)
            if keys==',': keys='Virgule' if french else 'Comma'
            if keys=='.': keys='Point' if french else 'Period'
            lines.append(keys+' : '+action.text())
    return '\n'.join(lines)

def guide_text(registry):
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'assets'
    return (root/('guide_'+language()+'.txt')).read_text(encoding='utf-8')+'\n\n'+'-'*40+'\n\n'+shortcut_lines(registry)+'\n'

def fill_browser(browser,registry):
    text=guide_text(registry)
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
