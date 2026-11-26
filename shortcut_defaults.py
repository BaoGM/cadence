# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QKeyCombination, Qt
from PySide6.QtGui import QKeySequence


KEYBOARD_LAYOUTS = ('QWERTY', 'AZERTY')
# The two rows at each level describe the same physical keys on French and US keyboards.
_ROWS = [
    ('`1234567890-=', "²&é\"'(-è_çà)="),
    ('QWERTYUIOP[]', 'AZERTYUIOP^$'),
    ("ASDFGHJKL;'", 'QSDFGHJKLMù'),
    ('ZXCVBNM,./', 'WXCVBN,;:!'),
    ('\\', '*'),
    ('!@#$%^&*()_', '1234567890°'),
    ('{}|:"<>?', '¨£µM%./§'),
]
_AZERTY = {ord(a.upper()):ord(b.upper()) for us,fr in _ROWS for a,b in zip(us,fr)}


def physical_shortcut(value, layout, source='QWERTY'):
    if not value or layout == source:
        return value
    mapping = _AZERTY if layout == 'AZERTY' else {b:a for a,b in _AZERTY.items() if a != ord(':')}
    sequence = QKeySequence(value, QKeySequence.SequenceFormat.PortableText)
    chords = []
    for index in range(sequence.count()):
        chord = sequence[index]
        key = chord.key()
        mapped = mapping.get(key.value, key.value)
        if layout == 'AZERTY' and key == Qt.Key.Key_Colon:
            chords.append(QKeyCombination(chord.keyboardModifiers() | Qt.KeyboardModifier.ShiftModifier, Qt.Key.Key_M))
        else:
            chords.append(QKeyCombination(chord.keyboardModifiers(), Qt.Key(mapped)))
    return QKeySequence(*chords).toString(QKeySequence.SequenceFormat.PortableText)


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
    'Références/Intervertir A / B':('X','Alt+X'),
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


def apply_aliases(registry,layout='QWERTY'):
    assigned=[action.shortcut() for action,_ in registry.values() if not action.shortcut().isEmpty()]
    for key,alternate in (('Aide/Guide rapide','?'),('Édition/Rétablir','Ctrl+Shift+Z')):
        action,default=registry[key]
        primary=action.shortcut()
        alias=QKeySequence(physical_shortcut(alternate,layout))
        if primary==QKeySequence(physical_shortcut(default,layout)) and not any(alias.matches(s)!=QKeySequence.NoMatch or s.matches(alias)!=QKeySequence.NoMatch for s in assigned):
            action.setShortcuts([primary,alias])
