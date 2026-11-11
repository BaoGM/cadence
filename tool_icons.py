# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import Qt,QRectF,QPointF
from PySide6.QtGui import QIcon,QPixmap,QPainter,QPen,QColor,QPainterPath,QPolygonF


def tool_icon(tool):
    icon=QIcon()
    for size in (16,24,32,48,64,96,128):
        pixmap=QPixmap(size,size); pixmap.fill(Qt.GlobalColor.transparent)
        p=QPainter(pixmap); p.setRenderHint(QPainter.RenderHint.Antialiasing); p.scale(size/32,size/32)
        color=QColor('#e4edf5'); p.setPen(QPen(color,1.8,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin)); p.setBrush(Qt.BrushStyle.NoBrush)
        if tool=='cursor':
            path=QPainterPath(QPointF(7,3)); path.lineTo(25,18); path.lineTo(17,19); path.lineTo(13,27); path.closeSubpath(); p.drawPath(path)
        elif tool=='arrow':
            p.drawLine(QPointF(5,26),QPointF(26,5)); p.drawLine(QPointF(13,5),QPointF(26,5)); p.drawLine(QPointF(26,5),QPointF(26,18))
        elif tool=='rectangle': p.drawRoundedRect(QRectF(6,6,20,20),1,1)
        elif tool=='ellipse': p.drawEllipse(QRectF(5,5,22,22))
        elif tool=='brush':
            path=QPainterPath(QPointF(12,19)); path.lineTo(23,4); path.quadTo(25,1,27,4); path.quadTo(29,6,26,8); path.lineTo(16,22); path.closeSubpath(); p.drawPath(path)
            path=QPainterPath(QPointF(12,19)); path.cubicTo(6,18,9,26,3,27); path.cubicTo(10,31,19,27,16,22); path.closeSubpath(); p.fillPath(path,color)
            p.drawLine(QPointF(14,16),QPointF(19,20))
        elif tool=='eraser':
            poly=QPolygonF([QPointF(4,20),QPointF(17,5),QPointF(28,15),QPointF(17,28),QPointF(12,28)]); p.drawPolygon(poly)
            p.drawLine(QPointF(10,13),QPointF(22,23)); p.drawLine(QPointF(17,28),QPointF(29,28))
        elif tool=='picker':
            path=QPainterPath(QPointF(18,9)); path.lineTo(7,20); path.lineTo(5,27); path.lineTo(12,25); path.lineTo(23,14); path.closeSubpath(); p.drawPath(path)
            p.drawLine(QPointF(15,6),QPointF(26,17)); p.setBrush(color); p.drawEllipse(QRectF(20,3,9,9))
        elif tool=='lasso':
            p.setPen(QPen(color,1.8,Qt.PenStyle.DashLine)); p.drawEllipse(QRectF(3,4,25,19)); p.setPen(QPen(color,1.8))
            path=QPainterPath(QPointF(10,21)); path.cubicTo(5,25,8,29,13,28); path.cubicTo(20,27,16,19,10,21); p.drawPath(path)
        elif tool=='resize':
            p.drawRect(QRectF(7,7,18,18))
            for x,y in ((5,5),(23,5),(23,23),(5,23)): p.fillRect(QRectF(x,y,5,5),color)
        elif tool=='crop':
            p.drawLine(QPointF(9,3),QPointF(9,24)); p.drawLine(QPointF(9,24),QPointF(30,24))
            p.drawLine(QPointF(3,9),QPointF(24,9)); p.drawLine(QPointF(24,9),QPointF(24,30))
        else:
            p.drawLine(QPointF(6,6),QPointF(26,6)); p.drawLine(QPointF(6,6),QPointF(6,10)); p.drawLine(QPointF(26,6),QPointF(26,10)); p.drawLine(QPointF(16,6),QPointF(16,27)); p.drawLine(QPointF(11,27),QPointF(21,27))
        p.end(); icon.addPixmap(pixmap)
    return icon
