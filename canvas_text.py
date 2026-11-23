# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QAbstractTextDocumentLayout, QColor, QPalette, QPen, QTextCursor, QTextOption, QTransform
from PySide6.QtWidgets import QApplication, QFrame, QTextEdit

from affine import qt
from draw_text import fitted_layout, make_font, text_bounds
from ui_text import tr


class CanvasTextEditor(QTextEdit):
    """Edit with Qt's native input methods and paint the document in the video compositor."""

    def __init__(self, controller, key, index, mark):
        super().__init__(controller.viewer)
        self.controller = controller
        self.project = controller.win.doc
        self.source = self.project.state.drawings
        self.key, self.index, self.mark = key, index, mark
        self.hidden_key = None
        if index is not None:
            marks = list(key.marks)
            marks[index] = replace(mark, opacity=0.)
            self.hidden_key = replace(key, marks=tuple(marks))
        height, width = controller.viewer.rgb.shape[:2]
        self.aspect = round(width/height, 8)
        self.canvas_width = self.aspect*1000.
        self.bounds = text_bounds(mark,self.canvas_width,1000.)
        self.anchor = QPointF(self.bounds.x()/self.canvas_width, self.bounds.y()/1000.)
        self.selecting = False
        self.blink = True
        self.setProperty('canvasTextInput',True)
        self.setAccessibleName(tr('Texte'))
        self.setAcceptRichText(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setStyleSheet('background:transparent;border:0;padding:0;')
        self.viewport().setAutoFillBackground(False)
        self.setFixedSize(1,1)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QTextEdit.LineWrapMode.FixedPixelWidth if mark.box else QTextEdit.LineWrapMode.NoWrap)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.document().setDocumentMargin(0.)
        self.setPlainText(mark.text)
        self.textChanged.connect(self.fit)
        self.cursorPositionChanged.connect(self.cursor_moved)
        self.selectionChanged.connect(controller.viewer.update)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.flash)
        self.moveCursor(QTextCursor.MoveOperation.End)

    def activate(self):
        viewer = self.controller.viewer
        viewer.presentationChanged.connect(self.place_input)
        self.previous_proxy = viewer.focusProxy()
        viewer.setFocusProxy(self)
        self.show()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        # The application stylesheet applies its widget font when QTextEdit first becomes visible.
        self.fit()

    def place_input(self):
        viewer=self.controller.viewer
        if self.controller.text_editor is not self or viewer.image is None: return
        size=viewer.image_size().scaled(viewer.size(),Qt.AspectRatioMode.KeepAspectRatio)
        rect=self.controller.a_rect(size)
        if rect is None: return
        cursor=self.textCursor()
        block=cursor.block()
        area=self.document().documentLayout().blockBoundingRect(block)
        line=block.layout().lineForTextPosition(cursor.positionInBlock())
        if not line.isValid(): return
        x=line.cursorToX(cursor.positionInBlock())[0]
        point=self.anchor+QPointF((area.x()+x)/self.canvas_width,(area.y()+line.y()+line.height())/1000)
        point=self.controller.selection.display_transform(rect).map(qt(self.mark.transform).map(point))
        view=QTransform()
        view.translate(viewer.width()/2+viewer.pan.x(),viewer.height()/2+viewer.pan.y())
        view.rotate(viewer.angle)
        view.scale(viewer.zoom,viewer.zoom)
        self.move(view.map(point).toPoint())

    def inputMethodQuery(self,query):
        if query==Qt.InputMethodQuery.ImCursorRectangle:
            return QRectF(0,0,1,1)
        return super().inputMethodQuery(query)

    def inputMethodEvent(self,event):
        super().inputMethodEvent(event)
        self.cursor_moved()

    def fit(self):
        text = self.toPlainText()
        if len(text)>10000:
            cursor=QTextCursor(self.document())
            cursor.setPosition(len(text[:10000].encode('utf-16-le'))//2)
            cursor.movePosition(QTextCursor.MoveOperation.End,QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            return
        if self.mark.box:
            font,_,rect = fitted_layout(replace(self.mark,text=text), self.aspect)
            self.setLineWrapColumnOrWidth(max(1,round(rect.width())))
        else:
            font = make_font(self.mark, round(self.mark.size*1000))
        self.document().setDefaultFont(font)
        self.cursor_moved()

    def cursor_moved(self):
        self.blink = True
        self.place_input()
        if hasattr(self,'timer') and QApplication.cursorFlashTime()>0:
            self.timer.start(max(100,QApplication.cursorFlashTime()//2))
        self.controller.viewer.update()

    def flash(self):
        self.blink = not self.blink
        self.controller.viewer.update()

    def paintEvent(self,event):
        # The native D3D child and the software renderer both draw the editor in paint().
        pass

    def paint(self,painter,rect):
        controller = self.controller
        painter.save()
        painter.setTransform(controller.selection.display_transform(rect), True)
        painter.setTransform(qt(self.mark.transform), True)
        painter.translate(self.anchor)
        painter.scale(1/self.canvas_width, .001)
        bounds = QRectF(0,0,self.bounds.width(),self.bounds.height())
        if not self.mark.box:
            bounds = bounds.united(QRectF(QPointF(), self.document().size()))
        pen = QPen(QColor('#7ce4d5'),1,Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(QColor(12,22,31,100))
        painter.drawRect(bounds)
        painter.setClipRect(bounds,Qt.ClipOperation.IntersectClip)
        context = QAbstractTextDocumentLayout.PaintContext()
        context.palette.setColor(QPalette.ColorRole.Text,QColor(self.mark.color))
        cursor = self.textCursor()
        if cursor.hasSelection():
            selected = QAbstractTextDocumentLayout.Selection()
            selected.cursor = cursor
            selected.format.setBackground(QColor('#3b7775'))
            selected.format.setForeground(QColor('#ffffff'))
            context.selections = [selected]
        elif self.blink:
            context.cursorPosition = cursor.position()
        self.document().documentLayout().draw(painter,context)
        painter.restore()

    def document_point(self, pos, extend=False):
        point = self.controller.point(pos,extend)
        if point is None: return None
        local = qt(self.mark.transform).inverted()[0].map(QPointF(*point))-self.anchor
        return QPointF(local.x()*self.canvas_width,local.y()*1000)

    def pointer(self,event):
        kind = event.type()
        if kind not in (QEvent.Type.MouseButtonPress,QEvent.Type.MouseButtonDblClick,
                        QEvent.Type.MouseMove,QEvent.Type.MouseButtonRelease): return False
        if kind==QEvent.Type.MouseMove and not self.selecting: return False
        if kind!=QEvent.Type.MouseMove and event.button()!=Qt.MouseButton.LeftButton: return False
        # The double-click that opened the editor still has a release to deliver.
        if kind==QEvent.Type.MouseButtonRelease:
            self.selecting=False
            return True
        point=self.document_point(event.position(),kind==QEvent.Type.MouseMove)
        bounds=QRectF(0,0,self.bounds.width(),self.bounds.height())
        if not self.mark.box: bounds=bounds.united(QRectF(QPointF(),self.document().size()))
        if point is None or (kind!=QEvent.Type.MouseMove and not bounds.contains(point)):
            self.finish(True)
            return True
        cursor=self.textCursor()
        position=self.document().documentLayout().hitTest(point,Qt.HitTestAccuracy.FuzzyHit)
        if position>=0:
            extend=kind==QEvent.Type.MouseMove or event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            cursor.setPosition(position,QTextCursor.MoveMode.KeepAnchor if extend else QTextCursor.MoveMode.MoveAnchor)
            if kind==QEvent.Type.MouseButtonDblClick: cursor.select(QTextCursor.SelectionType.WordUnderCursor)
            self.setTextCursor(cursor)
        self.selecting=True
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        return True

    def event(self,event):
        if event.type()==QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self,event):
        key=event.key()
        if key==Qt.Key.Key_Escape:
            self.finish(False)
        elif key in (Qt.Key.Key_Enter,Qt.Key.Key_Return):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.insertPlainText('\n')
            else:
                self.finish(True)
        else:
            super().keyPressEvent(event)
        event.accept()

    def focusOutEvent(self,event):
        super().focusOutEvent(event)
        if event.reason()!=Qt.FocusReason.PopupFocusReason:
            self.finish(True)

    def finish(self,commit):
        c=self.controller
        if c.text_editor is not self: return
        c.text_editor=None
        self.timer.stop()
        if c.viewer.focusProxy() is self:
            c.viewer.setFocusProxy(self.previous_proxy)
        if self.hasFocus(): c.viewer.setFocus(Qt.FocusReason.OtherFocusReason)
        self.hide()
        self.deleteLater()
        text=self.toPlainText()[:10000]
        if commit and self.project is c.win.doc and self.source is self.project.state.drawings:
            mark=replace(self.mark,text=text)
            if self.index is None and text.strip():
                key=replace(self.key,marks=self.key.marks+(mark,))
                c.commit_key(key,'Ajouter une zone de texte')
                c.select_text(len(key.marks)-1,key)
            elif self.index is not None and text!=self.mark.text:
                marks=list(self.key.marks)
                marks[self.index]=mark
                key=replace(self.key,marks=tuple(marks))
                c.commit_key(key,'Modifier le texte')
                c.select_text(self.index,key)
        c.invalidate()
