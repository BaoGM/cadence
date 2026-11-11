# SPDX-License-Identifier: GPL-3.0-only
"""Affine transforms in normalized image coordinates, independent of preview size."""
import math
from PySide6.QtGui import QTransform

IDENTITY=(1.,0.,0.,1.,0.,0.)
def compose(outer,inner):
    a,b,c,d,x,y=outer; e,f,g,h,u,v=inner
    return (a*e+c*f,b*e+d*f,a*g+c*h,b*g+d*h,a*u+c*v+x,b*u+d*v+y)
def qt(matrix): return QTransform(*matrix)
def pixel(matrix,w,h):
    a,b,c,d,x,y=matrix; return QTransform(a,b*h/w,c*w/h,d,x*w,y*h)
def translate(x,y): return (1.,0.,0.,1.,x,y)
def scale(x,y,center):
    return (x,0.,0.,y,center.x()*(1-x),center.y()*(1-y))
def rotate(angle,center,aspect):
    c,s=math.cos(math.radians(angle)),math.sin(math.radians(angle))
    return (c,s*aspect,-s/aspect,c,center.x()*(1-c)+s/aspect*center.y(),center.y()*(1-c)-s*aspect*center.x())
def valid(matrix):
    return len(matrix)==6 and all(isinstance(v,(int,float)) and math.isfinite(v) and abs(v)<=10000 for v in matrix) and abs(matrix[0]*matrix[3]-matrix[1]*matrix[2])>1e-10
