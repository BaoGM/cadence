# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import dataclass, replace
from bisect import bisect_right
import math
from affine import IDENTITY as AFFINE_IDENTITY,compose,pixel,valid

VECTOR_TOOLS=('arrow','rectangle','ellipse')

def vector_path(mark,width,height):
    from PySide6.QtCore import QPointF,QRectF
    from PySide6.QtGui import QPainterPath,QTransform
    path=QPainterPath()
    if len(mark.points)<2: return path
    a,b=mark.points[0],mark.points[-1]; x,y=a[0]*width,a[1]*height; xx,yy=b[0]*width,b[1]*height
    if mark.tool=='arrow':
        dx,dy=xx-x,yy-y; length=math.hypot(dx,dy)
        if length<.01: return path
        ux,uy=dx/length,dy/length; head=min(length*.45,max(8,mark.size*height*4))
        path.moveTo(x,y); path.lineTo(xx,yy)
        path.moveTo(xx-ux*head-uy*head*.5,yy-uy*head+ux*head*.5); path.lineTo(xx,yy); path.lineTo(xx-ux*head+uy*head*.5,yy-uy*head-ux*head*.5)
    else:
        rect=QRectF(QPointF(x,y),QPointF(xx,yy)).normalized()
        if mark.tool=='rectangle': path.addRect(rect)
        else: path.addEllipse(rect)
    if mark.angle:
        transform=QTransform(); transform.translate(x,y); transform.rotate(mark.angle); transform.translate(-x,-y)
        path=transform.map(path)
    return path

@dataclass(frozen=True)
class Mark:
    tool: str = 'brush'
    points: tuple = ()
    size: float = .01
    color: str = '#ff7043'
    opacity: float = 1.
    pressure: bool = True
    sensitivity: float = 1.
    text: str = ''
    font_family: str = 'Arial'
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikeout: bool = False
    box: tuple[float,float] | None = None
    children: tuple = ()
    angle: float = 0.
    transform: tuple = AFFINE_IDENTITY

@dataclass(frozen=True)
class DrawingKey:
    start: int
    end: int
    marks: tuple[Mark, ...] = ()


def active_key(keys, frame):
    index=bisect_right(keys,frame,key=lambda key:key.start)-1
    return keys[index] if index>=0 and frame<keys[index].end else None


def nearby_keys(keys,frame,before=0,after=0):
    from timeline_index import visible_keys
    return visible_keys(keys,frame-before+1,frame+after)


def put_key(keys, key):
    """Overwrite an exposure, preserving both sides of intersecting exposures."""
    if key.start < 0 or key.end <= key.start: raise ValueError('Plage de dessin invalide.')
    result = []
    for old in keys:
        if old.end <= key.start or old.start >= key.end: result.append(old)
        else:
            if old.start < key.start: result.append(replace(old,end=key.start))
            if old.end > key.end: result.append(replace(old,start=key.end))
    return tuple(sorted(result+[key],key=lambda k:k.start))


def load_keys(data,depth=0):
    if depth>64: raise ValueError("Dessin trop imbriqué.")
    result=[]
    for raw in data:
        start,end=raw['start'],raw['end']
        if not isinstance(start,int) or not isinstance(end,int) or not 0<=start<end<=100000000: raise ValueError('Clé de dessin invalide.')
        marks=[]
        for m in raw['marks']:
            children=load_keys([dict(start=0,end=1,marks=m['children'])],depth+1)[0].marks if m.get('children') else ()
            mark=Mark(**{**m,'children':children,'points':tuple(tuple(p) for p in m['points']),'box':tuple(m['box']) if m.get('box') else None,'transform':tuple(m.get('transform',AFFINE_IDENTITY))})
            if not valid(mark.transform): raise ValueError('Transformation de dessin invalide.')
            if not isinstance(mark.font_family,str) or not 1<=len(mark.font_family)<=256 or any(type(v) is not bool for v in (mark.bold,mark.italic,mark.underline,mark.strikeout)): raise ValueError('Style de texte invalide.')
            if mark.box is not None and (len(mark.box)!=2 or any(not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<v<=9 for v in mark.box)): raise ValueError('Zone de texte invalide.')
            if mark.tool not in ('brush','eraser','text','group')+VECTOR_TOOLS: raise ValueError('Outil de dessin invalide.')
            if mark.tool in VECTOR_TOOLS and len(mark.points)!=2: raise ValueError('Forme vectorielle invalide.')
            if not isinstance(mark.angle,(int,float)) or not math.isfinite(mark.angle) or not -180<=mark.angle<=180: raise ValueError('Rotation de dessin invalide.')
            if not all(math.isfinite(v) for v in (mark.size,mark.opacity,mark.sensitivity)) or not (0<mark.size<=2 and 0<=mark.opacity<=1 and .1<=mark.sensitivity<=5): raise ValueError('Paramètre de dessin invalide.')
            if len(mark.color)!=7 or mark.color[0]!='#': raise ValueError('Couleur invalide.')
            int(mark.color[1:],16)
            if not isinstance(mark.text,str) or len(mark.text)>10000: raise ValueError('Texte invalide.')
            if not mark.points or any(len(p)!=3 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in p) or not (-4<=p[0]<=5 and -4<=p[1]<=5 and 0<=p[2]<=1) for p in mark.points): raise ValueError('Points de dessin invalides.')
            if (mark.tool=='group')!=bool(mark.children): raise ValueError('Groupe de dessin invalide.')
            marks.append(mark)
        result.append(DrawingKey(start,end,tuple(marks)))
    result.sort(key=lambda k:k.start)
    if any(a.end>b.start for a,b in zip(result,result[1:])): raise ValueError('Clés de dessin superposées.')
    return tuple(result)


def pressure_size(mark,pressure):
    return max(.03, max(0.,min(1.,pressure)) ** mark.sensitivity) if mark.pressure else 1.


def ink_bounds(mark,width,height,outer=AFFINE_IDENTITY):
    from PySide6.QtCore import QPointF,QRect,QRectF
    transform=compose(outer,mark.transform); canvas=QRect(0,0,width,height)
    if mark.children:
        area=QRect()
        for child in mark.children: area=area.united(ink_bounds(child,width,height,transform))
        return area
    if mark.tool in VECTOR_TOOLS:
        radius=max(.5,mark.size*height)/2
        bounds=vector_path(mark,width,height).boundingRect().adjusted(-radius,-radius,radius,radius)
    elif mark.tool!='text' and mark.points:
        xs=[point[0]*width for point in mark.points]; ys=[point[1]*height for point in mark.points]
        radius=max(.35,mark.size*height/2)
        bounds=QRectF(QPointF(min(xs)-radius,min(ys)-radius),QPointF(max(xs)+radius,max(ys)+radius))
    else: return canvas
    return pixel(transform,width,height).mapRect(bounds).adjusted(-2,-2,2,2).toAlignedRect().intersected(canvas)


def render_marks_region(marks,width,height):
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage
    area=QRect()
    for mark in marks: area=area.united(ink_bounds(mark,width,height))
    return (area.x(),area.y()),render_marks(marks,width,height,_area=area) if not area.isEmpty() else QImage()


def render_marks(marks,width,height,outer=AFFINE_IDENTITY,_area=None):
    from PySide6.QtCore import Qt,QPointF,QRect
    from PySide6.QtGui import QImage,QPainter,QColor,QPen,QTransform
    canvas=QRect(0,0,width,height) if _area is None else _area
    image=QImage(canvas.size(),QImage.Format.Format_ARGB32_Premultiplied); image.fill(Qt.GlobalColor.transparent)
    for mark in marks:
        transform=compose(outer,mark.transform)
        if mark.tool=='group':
            ink=render_marks(mark.children,width,height,transform,_area=canvas)
            p=QPainter(image); p.setOpacity(mark.opacity); p.drawImage(0,0,ink); p.end(); continue
        # A stroke is composited once: overlapping samples do not darken it.
        matrix=pixel(transform,width,height); area=ink_bounds(mark,width,height,outer).intersected(canvas)
        if area.isEmpty(): continue
        ink=QImage(area.size(),QImage.Format.Format_ARGB32_Premultiplied); ink.fill(Qt.GlobalColor.transparent)
        matrix=QTransform(matrix.m11(),matrix.m12(),matrix.m21(),matrix.m22(),matrix.dx()-area.x(),matrix.dy()-area.y())
        p=QPainter(ink); p.setRenderHint(QPainter.RenderHint.Antialiasing); p.setTransform(matrix)
        color=QColor(mark.color); p.setPen(Qt.PenStyle.NoPen); p.setBrush(color)
        if mark.tool=='text':
            from draw_text import paint_text
            p.setPen(color); paint_text(p,mark,width,height)
        elif mark.tool in VECTOR_TOOLS:
            p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(QPen(color,max(.5,mark.size*height),Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
            p.drawPath(vector_path(mark,width,height))
        else:
            from native_render import paint_stroke
            native_stroke=paint_stroke(p,mark,width,height)
            points=mark.points
            for i,(x,y,pressure) in enumerate(() if native_stroke else points):
                r=max(.35,mark.size*height*pressure_size(mark,pressure)/2)
                if i:
                    x0,y0,p0=points[i-1]; r0=max(.35,mark.size*height*pressure_size(mark,p0)/2)
                    distance=math.hypot((x-x0)*width,(y-y0)*height)
                    steps=max(1,math.ceil(distance/max(.5,min(r,r0)*.4)))
                    for j in range(1,steps+1):
                        t=j/steps; radius=r0+(r-r0)*t
                        p.drawEllipse(QPointF((x0+(x-x0)*t)*width,(y0+(y-y0)*t)*height),radius,radius)
                else: p.drawEllipse(QPointF(x*width,y*height),r,r)
        p.end()
        p=QPainter(image); p.setOpacity(mark.opacity)
        if mark.tool=='eraser': p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
        p.drawImage(area.topLeft()-canvas.topLeft(),ink); p.end()
    return image


def layer_keys(keys,frame,before=0,after=0,ghost_opacity=.3):
    current=active_key(keys,frame); ghosts=[]
    for key in nearby_keys(keys,frame,before,after):
        if key is current or not key.marks: continue
        if key.end<=frame:
            distance=frame-key.end+1; radius=before
        else:
            distance=key.start-frame; radius=after
        if radius and 1<=distance<=radius: ghosts.append((distance,ghost_opacity*(radius-distance+1)/(radius+1),key))
    layers=[(key,opacity) for _,opacity,key in sorted(ghosts,key=lambda item:item[0],reverse=True)]
    if current: layers.append((current,1.))
    return layers


def render_layer(keys,frame,width,height,before=0,after=0,ghost_opacity=.3,cache=None,region=False):
    from PySide6.QtCore import Qt,QRect
    from PySide6.QtGui import QPainter,QImage
    from contextlib import nullcontext
    layers=layer_keys(keys,frame,before,after,ghost_opacity)
    priority=[key.marks for key,_ in reversed(layers)]
    raster=cache.render_region if cache is not None else render_marks_region
    area=QRect() if region else QRect(0,0,width,height)
    if region:
        for key,_ in layers:
            if cache is not None: area=area.united(cache.bounds(key.marks,width,height))
            else:
                for mark in key.marks: area=area.united(ink_bounds(mark,width,height))
    image=QImage(area.size(),QImage.Format.Format_ARGB32_Premultiplied); image.fill(Qt.GlobalColor.transparent)
    if not image.isNull():
        p=QPainter(image)
        try:
            with cache.batch(priority,width,height) if cache is not None else nullcontext():
                for key,opacity in layers:
                    origin,ink=raster(key.marks,width,height)
                    p.setOpacity(opacity); p.drawImage(origin[0]-area.x(),origin[1]-area.y(),ink)
        finally: p.end()
    return ((area.x(),area.y()),image) if region else image


def slice_keys(keys,start,end,offset=0):
    return tuple(replace(k,start=max(k.start,start)+offset,end=min(k.end,end)+offset) for k in keys if k.start<end and k.end>start)


def remove_key_range(keys,start,end,ripple=False):
    limit=max([end]+[k.end for k in keys])
    return slice_keys(keys,0,start)+slice_keys(keys,end,limit,-(end-start) if ripple else 0)


def insert_keys(keys,at,duration,block=()):
    limit=max([at]+[k.end for k in keys])
    return slice_keys(keys,0,at)+tuple(replace(k,start=k.start+at,end=k.end+at) for k in block)+slice_keys(keys,at,limit,duration)


def overlay_keys(base,added):
    boundaries=sorted({value for key in base+added for value in (key.start,key.end)})
    result=[]; i=j=0
    for start,end in zip(boundaries,boundaries[1:]):
        while i<len(base) and base[i].end<=start: i+=1
        while j<len(added) and added[j].end<=start: j+=1
        a=base[i] if i<len(base) and base[i].start<=start else None
        b=added[j] if j<len(added) and added[j].start<=start else None
        if a is None and b is None: continue
        if a and b and a.marks and b.marks:
            marks=tuple(Mark(tool='group',points=((0.,0.,1.),),children=k.marks) for k in (a,b))
        else: marks=(b.marks if b and b.marks else a.marks if a else ())
        result.append(DrawingKey(start,end,marks))
    return tuple(result)


def relocate_keys(keys,start,end,destination,length):
    """Move only the selected exposure interval. Reject collisions, never discard other art."""
    if not 0<=start<end<=length: return keys
    destination=max(0,min(int(destination),length-(end-start))); delta=destination-start
    if delta==0: return keys
    block=slice_keys(keys,start,end,delta)
    if not block: return keys
    rest=remove_key_range(keys,start,end)
    if any(a.start<b.end and b.start<a.end for a in block for b in rest): return keys
    return tuple(sorted(rest+block,key=lambda k:k.start))


def resize_key(keys,start,new_start,new_end,length):
    key=next((k for k in keys if k.start==start),None)
    if key is None: return keys
    low=max([0]+[k.end for k in keys if k.end<=key.start]); high=min([length]+[k.start for k in keys if k.start>=key.end])
    new_start=max(low,min(int(new_start),key.end-1)); new_end=min(high,max(int(new_end),new_start+1))
    if new_end<=new_start: return keys
    return tuple(sorted((replace(k,start=new_start,end=new_end) if k is key else k for k in keys),key=lambda k:k.start))


def mark_points(mark):
    return tuple(p for child in mark.children for p in mark_points(child)) if mark.children else mark.points

def translate_mark(mark,dx,dy):
    if mark.transform!=AFFINE_IDENTITY:
        from affine import translate
        return replace(mark,transform=compose(translate(dx,dy),mark.transform))
    return replace(mark,points=mark.points if mark.children else tuple((x+dx,y+dy,p) for x,y,p in mark.points),
                   children=tuple(translate_mark(child,dx,dy) for child in mark.children))

def move_erased_selection(marks,indices,dx,dy):
    # Isolate selected ink together with subsequent erase operations. Keeping the
    # masks INSIDE this vector group preserves soft erasing across overlapping ink,
    # and prevents a moved eraser from affecting unrelated drawings.
    chosen=set(indices)
    needs_group=any(m.tool=='eraser' and any(j<i for j in chosen) for i,m in enumerate(marks))
    if not needs_group:
        return tuple(translate_mark(m,dx,dy) if i in chosen else m for i,m in enumerate(marks)),tuple(indices)
    selected=tuple(m for i,m in enumerate(marks) if i in chosen or (m.tool=='eraser' and any(j<i for j in chosen)))
    remaining=tuple(m for i,m in enumerate(marks) if i not in chosen)
    group=Mark(tool='group',points=((0.,0.,1.),),children=selected)
    return remaining+(translate_mark(group,dx,dy),),(len(remaining),)
