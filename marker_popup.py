# SPDX-License-Identifier: GPL-3.0-only
from bisect import bisect_left
from math import ceil

from PySide6.QtCore import QEvent, QMimeData, QObject, QRect, QTimer, Qt, Signal
from PySide6.QtGui import QAbstractTextDocumentLayout, QGuiApplication, QKeySequence, QPainter, QTextCursor, QTextDocument, QTextOption
from PySide6.QtWidgets import QApplication, QStyle
from review_editor import ReviewEditor
from review_format import box_positions


class MarkerPopup(ReviewEditor):
    checkboxChanged=Signal(str,str)

    def __init__(self, timeline):
        super().__init__(timeline)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setReadOnly(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.setStyleSheet('QTextEdit {background:#202b36;color:#e6edf3;selection-background-color:#365f68;'
                           'selection-color:#ffffff;border:1px solid #516372;border-radius:4px;}')
        self.document().setDocumentMargin(8)
        self.boxes=()

    def present(self, text, anchor, styles=()):
        screen = QGuiApplication.screenAt(anchor.center()) or self.screen()
        bounds = screen.availableGeometry().adjusted(4, 4, -4, -4)
        self.load(text,styles)
        self.boxes=tuple(box_positions(text))
        self.ensurePolished()
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        decoration = self.size() - self.maximumViewportSize()
        # The live editor rewraps to its current viewport while measuring.
        layout = self.document().clone()
        layout.setTextWidth(-1)
        width = min(460, bounds.width(), max(92, ceil(layout.idealWidth()) + decoration.width() + 2))
        layout.setTextWidth(max(1, width - decoration.width()))
        measured = ceil(layout.size().height()) + decoration.height() + 2
        limit=measured
        block=layout.begin()
        count=0
        while block.isValid():
            lines=block.layout()
            if count+lines.lineCount()>=15 and (count+lines.lineCount()>15 or block.next().isValid()):
                line=lines.lineAt(14-count)
                limit=ceil(layout.documentLayout().blockBoundingRect(block).top()+line.y()+line.height()+layout.documentMargin())+decoration.height()+2
                break
            count+=lines.lineCount()
            block=block.next()
        height=min(measured,limit,bounds.height())
        if measured>height:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
            width=min(bounds.width(),width+self.style().pixelMetric(QStyle.PM_ScrollBarExtent))
        left = max(bounds.left(), min(anchor.left(), bounds.right() - width + 1))
        top = anchor.top() - height
        if top < bounds.top():
            top = min(anchor.bottom() + 1, bounds.bottom() - height + 1)
        top = max(bounds.top(), min(top, bounds.bottom() - height + 1))
        self.setGeometry(left, top, width, height)
        self.show()
        self.document().setTextWidth(self.viewport().width())
        self.verticalScrollBar().setValue(0)

    def paintEvent(self,event):
        cursor=self.textCursor()
        start,end=cursor.selectionStart(),cursor.selectionEnd()
        left=bisect_left(self.boxes,start)
        right=bisect_left(self.boxes,end)
        if left==right: return super().paintEvent(event)
        # QTextEdit normally paints one continuous selection, including embedded checkboxes.
        ctx=QAbstractTextDocumentLayout.PaintContext()
        ctx.palette=self.palette()
        dx,dy=self.horizontalScrollBar().value(),self.verticalScrollBar().value()
        ctx.clip=event.rect().translated(dx,dy)
        selections=[]
        for boundary in (*self.boxes[left:right],end):
            if start<boundary:
                part=QAbstractTextDocumentLayout.Selection()
                c=QTextCursor(self.document()); c.setPosition(start); c.setPosition(boundary,QTextCursor.KeepAnchor)
                part.cursor=c
                fmt=part.format
                fmt.setBackground(ctx.palette.highlight()); fmt.setForeground(ctx.palette.highlightedText())
                part.format=fmt
                selections.append(part)
            start=boundary+1
        ctx.selections=selections
        painter=QPainter(self.viewport())
        painter.translate(-dx,-dy)
        self.document().documentLayout().draw(painter,ctx)
        painter.end()

    def createMimeDataFromSelection(self):
        cursor=self.textCursor()
        if bisect_left(self.boxes,cursor.selectionStart())==bisect_left(self.boxes,cursor.selectionEnd()):
            return super().createMimeDataFromSelection()
        doc=QTextDocument()
        copy=QTextCursor(doc)
        copy.insertFragment(cursor.selection())
        for pos in reversed(tuple(box_positions(doc.toPlainText()))):
            copy.setPosition(pos)
            copy.deleteChar()
        mime=QMimeData(); mime.setText(doc.toPlainText()); mime.setHtml(doc.toHtml())
        return mime

    def toggle_box(self,position):
        before=self.toPlainText()
        super().toggle_box(position)
        self.checkboxChanged.emit(before,self.toPlainText())

    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:
            self.activateWindow()
            self.setFocus(Qt.MouseFocusReason)
        super().mousePressEvent(event)

    def event(self,event):
        if event.type()==QEvent.ShortcutOverride and (
            event.matches(QKeySequence.Copy) or event.matches(QKeySequence.SelectAll) or event.key()==Qt.Key_Escape
        ):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self,event):
        if event.key()==Qt.Key_Escape:
            self.parentWidget().marker_hover.cancel()
            event.accept()
            return
        super().keyPressEvent(event)


class MarkerHover(QObject):
    checkboxChanged=Signal(int,str,str)

    def __init__(self, timeline):
        super().__init__(timeline)
        self.timeline = timeline
        self.enabled = True
        self.popup = None
        self.frame = None
        self.wake = QTimer(self, singleShot=True, interval=350)
        self.wake.timeout.connect(self.show_note)
        self.dismiss = QTimer(self, singleShot=True, interval=220)
        self.dismiss.timeout.connect(self.dismiss_if_idle)
        timeline.installEventFilter(self)
        QGuiApplication.instance().applicationStateChanged.connect(self.app_state_changed)

    def app_state_changed(self,state):
        if state!=Qt.ApplicationActive:
            self.cancel()

    def dismiss_if_idle(self):
        if QApplication.activePopupWidget() or QApplication.mouseButtons() & Qt.LeftButton:
            self.dismiss.start()
            return
        if self.popup and self.popup.hasFocus() and self.popup.textCursor().hasSelection():
            return
        self.cancel()

    def set_enabled(self, enabled):
        self.enabled = enabled
        if not enabled:
            self.cancel()

    def cancel(self):
        self.wake.stop()
        self.dismiss.stop()
        self.frame = None
        if self.popup and self.popup.isVisible():
            self.popup.hide()

    def covers(self, point):
        return self.popup is not None and self.popup.isVisible() and self.popup.frameGeometry().contains(point)

    def update_comment(self):
        if self.frame is None or not self.popup or not self.popup.isVisible():
            return
        text=self.comment(self.frame)
        if not text:
            self.cancel()
            return
        styles=dict(self.timeline.state.marker_styles).get(self.frame,())
        if text!=self.popup.toPlainText() or styles!=self.popup.style_runs():
            scroll=self.popup.verticalScrollBar().value()
            self.popup.present(text,self.anchor,styles)
            self.popup.verticalScrollBar().setValue(scroll)

    def toggle_box(self,before,after):
        if self.frame is not None:
            self.checkboxChanged.emit(self.frame,before,after)
            self.update_comment()

    def show_note(self):
        t = self.timeline
        if self.frame is None or not t.isVisible() or not t.state:
            return
        text = self.comment(self.frame)
        if not text:
            return
        from timeline_skin import marker_areas
        for _, frame, flag, _ in marker_areas(t, self.point):
            if frame == self.frame:
                if self.popup is None:
                    self.popup = MarkerPopup(t)
                    self.popup.installEventFilter(self)
                    self.popup.checkboxChanged.connect(self.toggle_box)
                rect = flag.toAlignedRect()
                rect.moveLeft(round(self.point.x()))
                rect = QRect(t.mapToGlobal(rect.topLeft()), rect.size())
                self.anchor=rect
                self.popup.present(text,rect,dict(t.state.marker_styles).get(frame,()))
                return

    def comment(self, frame):
        notes = self.timeline.state.marker_notes
        idx = bisect_left(notes, (frame,))
        if idx < len(notes) and notes[idx][0] == frame and notes[idx][2].strip():
            return notes[idx][2]
        return ''

    def hover(self, marker, point):
        if not self.enabled:
            return
        self.point = point
        frame = marker[0] if marker else None
        if frame is None:
            self.leave()
            return
        self.dismiss.stop()
        if frame != self.frame:
            self.cancel()
            self.frame = frame
            self.wake.start()

    def leave(self):
        self.wake.stop()
        if self.popup and self.popup.isVisible():
            if not self.dismiss.isActive():
                self.dismiss.start()
        else:
            self.frame = None

    def eventFilter(self, obj, event):
        kind = event.type()
        if obj is self.timeline:
            if kind in (QEvent.Hide, QEvent.MouseButtonPress,
                        QEvent.Wheel, QEvent.Resize):
                self.cancel()
            elif kind == QEvent.Leave:
                self.leave()
        elif kind == QEvent.Enter:
            self.dismiss.stop()
        elif kind in (QEvent.Leave,QEvent.WindowDeactivate):
            self.dismiss.start()
        return False
