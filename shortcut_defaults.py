# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtGui import QKeySequence


REVISION=2
CHANGES={
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
    pending={key:new for key,(old,new) in CHANGES.items() if key in registry and isinstance(supplied.get(key,old),str) and QKeySequence(supplied.get(key,old))==QKeySequence(old)}
    result={key:value for key,value in supplied.items() if key not in pending}
    for key,value in pending.items():
        candidate=QKeySequence(value)
        conflict=any(candidate.matches(QKeySequence(saved))!=QKeySequence.SequenceMatch.NoMatch or QKeySequence(saved).matches(candidate)!=QKeySequence.SequenceMatch.NoMatch
            for other,saved in result.items() if other in registry and saved and isinstance(saved,str))
        result[key]='' if conflict else value
    return result
