# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtGui import QKeySequence


REVISION=4
CHANGES={
    'Affichage/Timecode / frames':('T','Alt+T'),
    'Dessin/Copier les clés':('Ctrl+Shift+C','C'),
    'Dessin/Coller les clés':('Ctrl+Shift+V','V'),
    'Dessin/Couper les clés':('Ctrl+Shift+X','X'),
    'Dessin/Supprimer les clés':('Shift+Delete','D'),
    'Outils/Curseur':('D','Q'),
    'Outils/Recadrer le clip':('C','Alt+C'),
    'Affichage/Flip - miroir vertical':('V','Shift+V'),
    'Comparaison/Intervertir A / B':('X','Alt+X'),
}


def migrate(supplied,registry,revision):
    if revision==REVISION: return supplied
    changes={} if revision==3 else dict(CHANGES)
    changes['Aide/Guide rapide']=('','F1')
    pending={key:new for key,(old,new) in changes.items() if key in registry and isinstance(supplied.get(key,old),str) and QKeySequence(supplied.get(key,old))==QKeySequence(old)}
    result={key:value for key,value in supplied.items() if key not in pending}
    for key,value in pending.items():
        candidate=QKeySequence(value)
        conflict=any(candidate.matches(QKeySequence(saved))!=QKeySequence.SequenceMatch.NoMatch or QKeySequence(saved).matches(candidate)!=QKeySequence.SequenceMatch.NoMatch
            for other,saved in result.items() if other in registry and saved and isinstance(saved,str))
        result[key]='' if conflict else value
    return result


def apply_aliases(registry):
    assigned=[action.shortcut() for action,_ in registry.values() if not action.shortcut().isEmpty()]
    for key,alternate in (('Aide/Guide rapide','?'),('Édition/Rétablir','Ctrl+Shift+Z')):
        action,default=registry[key]
        primary=action.shortcut()
        alias=QKeySequence(alternate)
        if primary==QKeySequence(default) and not any(alias.matches(s)!=QKeySequence.NoMatch or s.matches(alias)!=QKeySequence.NoMatch for s in assigned):
            action.setShortcuts([primary,alias])
