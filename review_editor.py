# SPDX-License-Identifier: GPL-3.0-only
import re
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QTextEdit
from review_format import BOXES, box_positions, style_runs, text_units
from timeline_skin import AMBER


BOLD, ITALIC, UNDERLINE, STRIKE = 1, 2, 4, 8


def flags(fmt):
    return (BOLD * (fmt.fontWeight() >= QFont.Weight.Bold) | ITALIC * fmt.fontItalic()
            | UNDERLINE * fmt.fontUnderline() | STRIKE * fmt.fontStrikeOut())


def set_flag(fmt, flag, enabled):
    if flag == BOLD:
        fmt.setFontWeight(QFont.Weight.Bold if enabled else QFont.Weight.Normal)
    elif flag == ITALIC:
        fmt.setFontItalic(enabled)
    elif flag == UNDERLINE:
        fmt.setFontUnderline(enabled)
    elif flag == STRIKE:
        fmt.setFontStrikeOut(enabled)


class CommentBoxHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.box_format = QTextCharFormat()
        self.box_format.setForeground(QColor(AMBER))
        self.box_format.setFontFamilies(['Segoe UI Symbol', 'Noto Sans Symbols 2', 'DejaVu Sans'])
        self.box_format.setFontStyleStrategy(QFont.StyleStrategy.NoFontMerging)

    def highlightBlock(self, text):
        for position in box_positions(text):
            self.setFormat(position, 1, self.box_format)


class ReviewEditor(QTextEdit):
    shortcuts = {Qt.Key_B:BOLD, Qt.Key_I:ITALIC, Qt.Key_U:UNDERLINE}

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setProperty('canvasTextInput',True)
        self.setTabChangesFocus(True)
        self._box_press = None
        self._box_highlighter = CommentBoxHighlighter(self.document())

    def style_runs(self):
        runs = []
        block = self.document().begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                style = flags(fragment.charFormat())
                if style:
                    start = fragment.position()
                    end = start + fragment.length()
                    if runs and runs[-1][1:] == (start,style):
                        runs[-1] = (runs[-1][0],end,style)
                    else:
                        runs.append((start,end,style))
                iterator += 1
            block = block.next()
        return style_runs(runs, self.toPlainText())

    def load(self, text, runs):
        self.clear()
        self.setCurrentCharFormat(QTextCharFormat())
        self.setPlainText(text)
        cursor = QTextCursor(self.document())
        for start,end,style in style_runs(runs, text):
            cursor.setPosition(start)
            cursor.setPosition(end,QTextCursor.KeepAnchor)
            fmt = QTextCharFormat()
            for flag in (BOLD,ITALIC,UNDERLINE,STRIKE):
                set_flag(fmt,flag,bool(style & flag))
            cursor.setCharFormat(fmt)
        cursor.setPosition(0)
        self.setTextCursor(cursor)

    def active_styles(self):
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return flags(self.currentCharFormat())
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        common = None
        block = self.document().findBlock(start)
        while block.isValid() and block.position() < end:
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                left = max(start, fragment.position())
                right = min(end, fragment.position() + fragment.length())
                if left < right:
                    cursor.setPosition(left)
                    cursor.setPosition(right, QTextCursor.KeepAnchor)
                    if cursor.selectedText().strip(''.join(BOXES)):
                        mask = flags(fragment.charFormat())
                        common = mask if common is None else common & mask
                        if not common:
                            return 0
                if right == end:
                    break
                iterator += 1
            block = block.next()
        return common

    def toggle_style(self,flag):
        cursor = self.textCursor()
        fmt = QTextCharFormat()
        active = self.active_styles()
        if active is None:
            return
        set_flag(fmt,flag,not (active & flag))
        if cursor.hasSelection():
            offset = cursor.selectionStart()
            text = cursor.selectedText()
            runs = style_runs([(0,text_units(text),flag)],text)
            if runs:
                cursor.beginEditBlock()
                for start,end,_ in runs:
                    cursor.setPosition(offset + start)
                    cursor.setPosition(offset + end,QTextCursor.KeepAnchor)
                    cursor.mergeCharFormat(fmt)
                cursor.endEditBlock()
        else:
            self.mergeCurrentCharFormat(fmt)
        self.currentCharFormatChanged.emit(self.currentCharFormat())
        self.setFocus()

    def insertFromMimeData(self,data):
        text = data.text()
        if not any(box in text for box in BOXES):
            return super().insertFromMimeData(data)
        cursor = self.textCursor()
        fmt = self.currentCharFormat()
        cursor.beginEditBlock()
        for part in re.split('([☐☑])',text):
            if part:
                cursor.insertText(part,QTextCharFormat() if part in BOXES else fmt)
        cursor.endEditBlock()
        self.setTextCursor(cursor)

    def event(self,event):
        if not self.isReadOnly() and event.type()==QEvent.ShortcutOverride and event.modifiers()==Qt.ControlModifier and event.key() in self.shortcuts:
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self,event):
        if not self.isReadOnly() and event.modifiers()==Qt.ControlModifier and event.key() in self.shortcuts:
            self.toggle_style(self.shortcuts[event.key()])
            event.accept()
            return
        if event.modifiers()==Qt.NoModifier and event.key()==Qt.Key_Space:
            cursor=self.textCursor()
            if not cursor.hasSelection() and self.document().characterAt(cursor.position()) in BOXES:
                self.toggle_box(cursor.position())
                return
        super().keyPressEvent(event)

    def add_box(self):
        cursor=self.textCursor()
        cursor.movePosition(QTextCursor.StartOfBlock)
        if self.document().characterAt(cursor.position()) in BOXES:
            self.toggle_box(cursor.position())
        else:
            fmt=cursor.charFormat()
            cursor.beginEditBlock()
            cursor.insertText(BOXES[0],QTextCharFormat())
            cursor.insertText(' ',fmt)
            cursor.endEditBlock()
            self.setTextCursor(cursor)
        self.setFocus()

    def box_at(self,point):
        cursor=self.cursorForPosition(point)
        for pos in (cursor.position(),cursor.position()-1):
            if pos<0 or self.document().characterAt(pos) not in BOXES:
                continue
            cursor.setPosition(pos)
            left=self.cursorRect(cursor)
            cursor.movePosition(QTextCursor.NextCharacter)
            right=self.cursorRect(cursor)
            if left.y()==right.y() and left.united(right).contains(point):
                return pos
        return None

    def toggle_box(self,pos):
        cursor=QTextCursor(self.document())
        cursor.setPosition(pos)
        cursor.movePosition(QTextCursor.NextCharacter,QTextCursor.KeepAnchor)
        cursor.insertText(BOXES[1] if cursor.selectedText()==BOXES[0] else BOXES[0],QTextCharFormat())

    def mousePressEvent(self,event):
        self._box_press=self.box_at(event.position().toPoint()) if event.button()==Qt.LeftButton else None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self,event):
        pos=self._box_press
        self._box_press=None
        super().mouseReleaseEvent(event)
        if pos is not None and event.button()==Qt.LeftButton and self.box_at(event.position().toPoint())==pos:
            self.toggle_box(pos)
