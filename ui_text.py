# SPDX-License-Identifier: GPL-3.0-only
"""Translation at UI boundaries; project data and shortcut identifiers stay stable."""
import json,os,re,sys
from pathlib import Path

_root=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'assets'
_language='fr'; _qt_translator=None
_pairs={}
for line in (_root/'ui_en.txt').read_text(encoding='utf-8').splitlines():
    if ' => ' in line:
        a,b=line.split(' => ',1); _pairs[a.replace('\\n','\n')]=b.replace('\\n','\n')
_prefixes=sorted(((a,b) for a,b in _pairs.items() if a.endswith(':')),key=lambda item:len(item[0]),reverse=True)
_french={
    'Ouvrir des vidéos…':'Ouvrir des médias…','Ouvrir des vidéos':'Ouvrir des médias',
    'Associer les vidéos et projets à cette version':'Associer les médias et projets à cette version',
    'Draw over':'Dessin','Time code':'Code temporel','Timecode':'Code temporel','Frames':'Images',
    'Timecode / frames':'Code temporel / images','Flop - miroir horizontal':'Miroir horizontal','Flip - miroir vertical':'Miroir vertical',
    'Mute':'Couper le son','Unmute':'Réactiver le son','Mute / Unmute':'Couper / Réactiver le son',
    'Overlay - transparence':'Superposition','Overlay':'Superposition','A devant B - bascule':'Premier plan',
    'Différence - négatif':'Différence','Timeline':'Timeline','Timeline allégée':'Timeline allégée',
    'Press shortcut':'Saisir un raccourci',
    'Afficher la timeline':'Afficher la timeline','Toute la timeline':'Toute la timeline',
    'Réinitialiser le canvas':'Réinitialiser la vue',
}
_wording=[('du canvas','de la vue'),('le canvas','la vue'),('scrubber','faire défiler'),('Scrub vidéo','Défilement vidéo'),('scrub','défilement'),('canvas','vue'),('Canvas','Vue'),('time code','code temporel'),('Shift','Maj'),('Mute / Unmute','Couper / Réactiver le son'),('Overlay - transparence','Superposition'),('Overlay','Superposition')]
_reverse={v:k for k,v in _pairs.items()}
_reverse.update({v:k for k,v in _french.items()})
for name in ('Fichier','Édition','Lecture','Affichage','Comparaison','Dessin','Outils','Synchronisation 3D','Aide'):
    _reverse[_pairs.get(name,name)]=name; _reverse[name]=name
_reverse.update({'Undo':'Annuler','Flip horizontally':'Flop - miroir horizontal','Flip vertically':'Flip - miroir vertical'})

def language(): return _language
def source(text): return _reverse.get(text,text)

def plain(text,lang):
    if lang=='fr':
        if text in _french: return _french[text]
        for old,new in _wording: text=text.replace(old,new)
        return text
    if text in _pairs: return _pairs[text]
    stripped=text.strip()
    if stripped in _pairs: return text[:len(text)-len(text.lstrip())]+_pairs[stripped]+text[len(text.rstrip()):]
    return text

_patterns=[]
for entry in json.loads((_root/'ui_patterns.json').read_text(encoding='utf-8')):
    parts=entry['parts'] if isinstance(entry,dict) else entry
    translated_values=frozenset(entry.get('translate',())) if isinstance(entry,dict) else frozenset()
    regex='(.*?)'.join(re.escape(part) for part in parts)
    _patterns.append((sum(map(len,parts)),re.compile('^'+regex+'$',re.S),parts,translated_values))
_patterns.sort(key=lambda item:item[0],reverse=True)

def tr(text):
    if isinstance(text,(list,tuple)): return [tr(item) for item in text]
    if not isinstance(text,str) or not text: return text
    if '/' in text:
        category,title=text.split('/',1)
        if category in ('Fichier','Édition','Lecture','Affichage','Comparaison','Dessin','Outils','Synchronisation 3D','Aide'):
            if _language=='en' and category=='Édition' and title=='Annuler': return 'Edit / Undo'
            return tr(category)+' / '+tr(title)
    if _language=='fr': return plain(text,'fr')
    # Accept already translated strings when an action is shared by two menus.
    if text in _reverse and text not in _pairs: return text
    translated=plain(text,'en')
    if translated!=text: return translated
    for _,pattern,parts,translated_values in _patterns:
        match=pattern.fullmatch(text)
        if match:
            values=match.groups(); out=plain(parts[0],'en')
            for index,(value,part) in enumerate(zip(values,parts[1:])):
                out+=(tr(value) if index in translated_values else value)+plain(part,'en')
            if out!=text: return out
    if '\n' in text: return '\n'.join(tr(line) for line in text.split('\n'))
    for original,translated in _prefixes:
        if text.startswith(original+' '): return translated+' '+plain(text[len(original)+1:],'en')
    # Compound tooltips and messages use independently translated lines.
    if ' · ' in text: return ' · '.join(tr(part) for part in text.split(' · '))
    return text

def initialize_language():
    global _language,_qt_translator
    from preferences import preference_path
    try:
        saved=json.loads(preference_path().read_text(encoding='utf-8'))
        wanted=saved.get('language','fr') if isinstance(saved,dict) else 'fr'
    except (OSError,ValueError,TypeError): wanted='fr'
    _language=os.environ.get('CADENCE_LANGUAGE',wanted)
    if _language not in ('fr','en'): _language='fr'
    from PySide6.QtCore import QTranslator,Qt,QLocale
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance(); app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs,True)
    QLocale.setDefault(QLocale('fr_FR' if _language=='fr' else 'en_GB'))
    if _qt_translator: app.removeTranslator(_qt_translator)
    _qt_translator=QTranslator(app)
    if _language=='fr' and _qt_translator.load(str(_root/'qtbase_fr.qm')): app.installTranslator(_qt_translator)
