# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QRectF


def paint_layers(painter,rect,keys,frame,width,height,before,after,opacity,cache,flip_h=False,flip_v=False,submit=None):
    from drawing import layer_keys
    layers=layer_keys(keys,frame,before,after,opacity)
    with cache.batch([key.marks for key,_ in reversed(layers)],width,height):
        painter.save()
        try:
            painter.translate(rect.center()); painter.scale(-1 if flip_h else 1,-1 if flip_v else 1)
            painter.translate(-rect.center())
            for key,alpha in layers:
                origin,image=cache.render_region(key.marks,width,height)
                if image.isNull() or alpha<=0: continue
                target=QRectF(rect.x()+origin[0]*rect.width()/width,rect.y()+origin[1]*rect.height()/height,image.width()*rect.width()/width,image.height()*rect.height()/height)
                if submit:
                    submit(painter,target,image,alpha)
                else:
                    painter.setOpacity(alpha); painter.drawImage(target,image)
        finally: painter.restore()


def collect_layer(painter,rect,image,opacity):
    clipped=rect.intersected(painter.clipBoundingRect()) if painter.hasClipping() else rect
    if clipped.isEmpty(): return None
    clip=((clipped.left()-rect.left())/rect.width(),(clipped.top()-rect.top())/rect.height(),(clipped.right()-rect.left())/rect.width(),(clipped.bottom()-rect.top())/rect.height())
    clip=tuple(max(0.,min(1.,value)) for value in clip)
    transform=painter.deviceTransform()
    corners=[transform.map(point) for point in (rect.topLeft(),rect.topRight(),rect.bottomLeft(),rect.bottomRight())]
    return image,tuple(value for point in corners for value in (point.x(),point.y())),opacity*painter.opacity(),clip
