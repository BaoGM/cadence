# SPDX-License-Identifier: GPL-3.0-only
"""Resolution-independent text layout shared by preview, hit testing and export."""
from functools import lru_cache
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QFont,QFontMetricsF,QTextLayout,QTextOption


def make_font(mark,pixels):
    font=QFont(mark.font_family); font.setPixelSize(max(1,int(pixels)))
    font.setBold(mark.bold); font.setItalic(mark.italic); font.setUnderline(mark.underline); font.setStrikeOut(mark.strikeout)
    return font


def wrap(text,font,width):
    layouts=[]; y=0.; widest=0.
    option=QTextOption(); option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    for paragraph in text.split('\n'):
        layout=QTextLayout(paragraph or ' ',font); layout.setTextOption(option); layout.beginLayout()
        while True:
            line=layout.createLine()
            if not line.isValid(): break
            line.setLineWidth(width); line.setPosition(QPointF(0,y)); y+=line.height(); widest=max(widest,line.naturalTextWidth())
        layout.endLayout(); layouts.append(layout)
    return layouts,y,widest


@lru_cache(maxsize=128)
def fitted_layout(mark,aspect):
    width,height=mark.box[0]*1000*aspect,mark.box[1]*1000
    # Use canonical coordinates to keep wrapping and auto-fit identical at export resolution.
    lo,hi=1,max(1,min(8192,int(height)))
    while lo<hi:
        mid=(lo+hi+1)//2; _,used,widest=wrap(mark.text,make_font(mark,mid),width)
        if used<=height and widest<=width+.01: lo=mid
        else: hi=mid-1
    font=make_font(mark,lo); layouts,used,_=wrap(mark.text,font,width)
    return font,layouts,QRectF(0,0,width,height)


def text_bounds(mark,width,height):
    x,y,_=mark.points[0]
    if mark.box: return QRectF(x*width,y*height,mark.box[0]*width,mark.box[1]*height)
    fm=QFontMetricsF(make_font(mark,round(mark.size*height))); bounds=QRectF()
    for row,line in enumerate(mark.text.splitlines()): bounds=bounds.united(fm.boundingRect(line).translated(x*width,y*height+mark.size*height*(row+1)*1.2))
    return bounds


def paint_text(painter,mark,width,height):
    x,y,_=mark.points[0]
    if mark.box:
        _,layouts,rect=fitted_layout(mark,round(width/height,8))
        painter.save(); painter.translate(x*width,y*height); painter.scale(height/1000,height/1000); painter.setClipRect(rect)
        for layout in layouts: layout.draw(painter,QPointF(0,0))
        painter.restore()
    else:
        painter.setFont(make_font(mark,round(mark.size*height)))
        for row,line in enumerate(mark.text.splitlines()): painter.drawText(QPointF(x*width,y*height+mark.size*height*(row+1)*1.2),line)
