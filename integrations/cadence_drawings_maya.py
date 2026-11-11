# SPDX-License-Identifier: GPL-3.0-only
from pathlib import Path
import shutil
import re


def write_exr(path, pixels):
    import numpy as np
    import struct
    import zlib
    height,width,_=pixels.shape
    def attribute(name,kind,value):
        return name.encode()+b'\0'+kind.encode()+b'\0'+struct.pack('<i',len(value))+value
    channels=b''.join(channel+b'\0'+struct.pack('<iB3xii',1,0,1,1) for channel in (b'A',b'B',b'G',b'R'))+b'\0'
    bounds=struct.pack('<iiii',0,0,width-1,height-1)
    header=struct.pack('<II',20000630,2)
    for name,kind,value in (
        ('channels','chlist',channels),('compression','compression',b'\x03'),
        ('dataWindow','box2i',bounds),('displayWindow','box2i',bounds),
        ('lineOrder','lineOrder',b'\0'),('pixelAspectRatio','float',struct.pack('<f',1.)),
        ('screenWindowCenter','v2f',struct.pack('<ff',0.,0.)),('screenWindowWidth','float',struct.pack('<f',1.))):
        header+=attribute(name,kind,value)
    header+=b'\0'
    count=(height+15)//16
    with path.open('wb') as stream:
        stream.write(header); stream.write(bytes(count*8)); offsets=[]
        for row in range(0,height,16):
            raw=pixels[row:row+16,:,(3,2,1,0)].transpose(0,2,1).astype('<f2').tobytes()
            values=np.frombuffer(raw,dtype=np.uint8)
            shuffled=np.concatenate((values[::2],values[1::2]))
            shuffled[1:]=shuffled[1:]-shuffled[:-1]+128
            compressed=zlib.compress(shuffled.tobytes(),4)
            block=compressed if len(compressed)<len(raw) else raw
            offsets.append(stream.tell()); stream.write(struct.pack('<ii',row,len(block))); stream.write(block)
        stream.seek(len(header)); stream.write(struct.pack('<'+'Q'*count,*offsets))


def prepare_images(c, sequence, folder, destination):
    if not sequence: return [],'Raw',[]
    if not c.colorManagementPrefs(query=True,cmEnabled=True):
        for item in sequence: shutil.copy2(folder/item['image'],destination/item['image'])
        return [item['image'] for item in sequence],'Raw',[(1.,0.)]*len(sequence)
    import ctypes
    import os
    import numpy as np
    import maya.api.OpenMaya as om
    import PyOpenColorIO as ocio
    config_path=os.path.expandvars(c.colorManagementPrefs(query=True,configFilePath=True))
    config_path=config_path.replace('<MAYA_RESOURCES>',str(Path(os.environ['MAYA_LOCATION'])/'resources'))
    config=ocio.Config.CreateFromFile(config_path)
    space=c.colorManagementPrefs(query=True,renderingSpaceName=True)
    transform=ocio.DisplayViewTransform(src=space,
        display=c.colorManagementPrefs(query=True,displayName=True),
        view=c.colorManagementPrefs(query=True,viewName=True),direction=ocio.TRANSFORM_DIR_INVERSE)
    processor=config.getProcessor(transform).getDefaultCPUProcessor()
    names=[]; adjustments=[]
    for item in sequence:
        image=om.MImage(); image.readFromFile(str(folder/item['image']))
        width,height=image.getSize()
        # MImage scanlines start at the bottom; OpenEXR scanlines start at the top.
        values=np.frombuffer(ctypes.string_at(image.pixels(),width*height*4),dtype=np.uint8).reshape(height,width,4)[::-1].astype(np.float32)/255.
        visible=values[:,:,3]>0
        colours=values[visible].copy()
        if len(colours):
            processor.applyRGBA(colours)
            values[visible]=colours
        # Invert the faded display colour first, then undo MImage's premultiplication for the plane.
        np.divide(values[:,:,:3],values[:,:,3:],out=values[:,:,:3],where=values[:,:,3:]>0)
        if not np.isfinite(values).all() or np.abs(values).max()>65504:
            raise ValueError('The Maya view transform cannot represent these drawing colours')
        name=Path(item['image']).with_suffix('.exr').name
        # VP2 image-plane textures clamp HDR values; restore their range with colour gain/offset.
        bias=float(min(0.,np.floor(values[:,:,:3].min())))
        gain=float(max(1.,np.ceil(values[:,:,:3].max())-bias))
        values[:,:,:3]=(values[:,:,:3]-bias)/gain
        write_exr(destination/name,values); names.append(name)
        adjustments.append((gain,bias))
    return names,space,adjustments


def cameras():
    import maya.cmds as c
    return [(c.listRelatives(shape,parent=True) or [shape])[0] for shape in (c.ls(type='camera',long=True) or [])][:64]


def image_groups(c,owner,camera):
    return [node for node in c.ls(type='network',long=True) or []
        if c.attributeQuery('cadenceOwner',node=node,exists=True)
        and c.attributeQuery('cadenceCamera',node=node,exists=True)
        and c.getAttr(node+'.cadenceOwner')==owner and c.getAttr(node+'.cadenceCamera')==camera]


def remove_images(c,nodes):
    for node in nodes:
        members=c.listConnections(node+'.drawings',source=True,destination=False) or []
        for member in members:
            if not c.objExists(member): continue
            children=c.listRelatives(member,children=True,fullPath=True) or []
            marked=c.attributeQuery('cadenceImported',node=member,exists=True)
            planes=[child for child in children if c.nodeType(child)=='imagePlane' and
                (c.attributeQuery('cadenceImported',node=child,exists=True) if marked else
                 re.fullmatch(r'Cadence_(drawing|ghost)\d*Shape\d*',child.rsplit('|',1)[-1]))]
            if children and len(children)!=len(planes):
                if planes: c.delete(planes)
            else: c.delete(member)
        if c.objExists(node): c.delete(node)


def remove_blue(c,owner,shape):
    if not c.pluginInfo('bluePencil',query=True,loaded=True) or not c.bluePencilNode(exists=True): return
    camera=(c.listRelatives(shape,parent=True) or [''])[0]
    prefix='Cadence_'+owner+'_'
    for index in reversed(range(c.bluePencilLayer(camera,count=True))):
        if c.bluePencilLayer(camera,queryName=index).startswith(prefix): c.bluePencilLayer(camera,delete=index)


def prune_blue_node(c,removed=False):
    if not c.pluginInfo('bluePencil',query=True,loaded=True) or not c.bluePencilNode(exists=True): return
    for camera_shape in c.ls(type='camera',long=True) or []:
        camera=(c.listRelatives(camera_shape,parent=True) or [camera_shape])[0]
        if c.bluePencilLayer(camera,count=True): return
    for shape in c.ls(type='bluePencil',long=True) or []:
        if not removed and not c.attributeQuery('cadenceImported',node=shape,exists=True): continue
        parent=(c.listRelatives(shape,parent=True,fullPath=True) or [None])[0]
        nodes=[shape]+([parent] if parent else [])
        if any(c.referenceQuery(node,isNodeReferenced=True) or c.lockNode(node,query=True,lock=True)[0]
               or set(c.listAttr(node,userDefined=True) or [])-{'cadenceImported'} for node in nodes): continue
        if parent and c.listRelatives(parent,children=True,fullPath=True)==[shape]: c.delete(parent)
        else: c.delete(shape)


def clear():
    import maya.cmds as c
    selection=c.ls(selection=True,long=True) or []
    c.undoInfo(openChunk=True,chunkName='Remove Cadence drawings')
    try:
        removed=False
        if c.pluginInfo('bluePencil',query=True,loaded=True) and c.bluePencilNode(exists=True):
            for shape in c.ls(type='camera',long=True) or []:
                camera=(c.listRelatives(shape,parent=True) or [''])[0]
                for index in reversed(range(c.bluePencilLayer(camera,count=True))):
                    if re.fullmatch(r'Cadence_[0-9a-f]{32}_[0-9a-f]{8}',c.bluePencilLayer(camera,queryName=index)):
                        c.bluePencilLayer(camera,delete=index)
                        removed=True
        prune_blue_node(c,removed)
        groups=[node for node in c.ls(type='network',long=True) or []
            if all(c.attributeQuery(attr,node=node,exists=True) for attr in ('cadenceOwner','cadenceCamera','drawings'))
            and re.fullmatch('[0-9a-f]{32}',c.getAttr(node+'.cadenceOwner') or '')]
        remove_images(c,groups)
    finally:
        c.undoInfo(closeChunk=True)
        c.select([node for node in selection if c.objExists(node)],replace=True) if selection else c.select(clear=True)


def apply(data,folder):
    import maya.cmds as c
    camera=data['camera']
    if not c.objExists(camera): raise ValueError('Selected camera no longer exists')
    if c.nodeType(camera)=='transform':
        shapes=c.listRelatives(camera,shapes=True,type='camera',fullPath=True) or []
        if not shapes: raise ValueError('Selected object is not a camera')
        camera=shapes[0]
    if c.nodeType(camera)!='camera': raise ValueError('Selected object is not a camera')
    if data['mode']=='blue_pencil': return blue_pencil(data,folder,camera)
    if data['mode']!='images': raise ValueError('Maya supports transparent drawing images')
    owner=data['owner']; selection=c.ls(selection=True,long=True) or []
    project=Path(c.workspace(query=True,rootDirectory=True))
    destination=project/'sourceimages'/'Cadence'/owner/data['revision']
    destination.mkdir(parents=True,exist_ok=True)
    sequence=data.get('sequence',[])
    if data['keys'] and not sequence: raise ValueError('Update Cadence before transferring images')
    filenames,color_space,adjustments=prepare_images(c,sequence,folder,destination)
    old=image_groups(c,owner,camera)
    created=[]
    c.undoInfo(openChunk=True,chunkName='Cadence drawings')
    try:
        group=c.createNode('network',name='Cadence_drawings'); created.append(group)
        for name,value in (('cadenceOwner',owner),('cadenceCamera',camera)):
            c.addAttr(group,longName=name,dataType='string'); c.setAttr(group+'.'+name,value,type='string')
        c.addAttr(group,longName='drawings',attributeType='message',multi=True)
        near=c.getAttr(camera+'.nearClipPlane'); far=c.getAttr(camera+'.farClipPlane')
        depth=max(near*2,1.)
        if depth>=far: raise ValueError('Camera clipping range is too small')
        if sequence:
            transform,shape=c.imagePlane(camera=camera,fileName=(destination/filenames[0]).as_posix(),name='Cadence_drawing',showInAllViews=False)
            created.append(transform)
            for node in (transform,shape):
                c.addAttr(node,longName='cadenceImported',attributeType='bool',defaultValue=True)
            c.connectAttr(transform+'.message',group+'.drawings[0]')
            c.setAttr(shape+'.depth',depth)
            c.setAttr(shape+'.fit',1)
            c.setAttr(shape+'.displayMode',3)
            c.setAttr(shape+'.frameVisibility',False)
            c.setAttr(shape+'.ignoreColorSpaceFileRules',True)
            c.setAttr(shape+'.colorSpace',color_space,type='string')
            c.setAttr(shape+'.useFrameExtension',True)
            # Maya connects new image planes to scene time; replace that connection with sparse exposures.
            plug=shape+'.frameExtension'
            for source in c.listConnections(plug,source=True,destination=False,plugs=True) or []:
                c.disconnectAttr(source,plug)
                node=source.split('.')[0]
                if c.nodeType(node)=='timeToUnitConversion' and not c.listConnections(node,source=False,destination=True): c.delete(node)
            curves=[]
            for slot,attribute in enumerate(('colorGain','colorOffset'),1):
                curve=c.createNode('animCurveTU',name='Cadence_'+attribute); created.append(curve); curves.append(curve)
                c.connectAttr(curve+'.message',group+'.drawings[%d]'%slot)
                for channel in 'RGB': c.connectAttr(curve+'.output',shape+'.'+attribute+channel)
            for index,item in enumerate(sequence):
                c.setKeyframe(shape,attribute='frameExtension',time=item['frame'],value=index,inTangentType='flat',outTangentType='step')
                gain,bias=adjustments[index]
                for curve,value in zip(curves,(gain,bias)):
                    c.setKeyframe(curve,time=item['frame'],value=value,inTangentType='flat',outTangentType='step')
        remove_blue(c,owner,camera)
        remove_images(c,old)
    except BaseException:
        for node in reversed(created):
            if c.objExists(node): c.delete(node)
        raise
    finally:
        c.undoInfo(closeChunk=True)
        if selection: c.select([node for node in selection if c.objExists(node)],replace=True)
        else: c.select(clear=True)
    return dict(keys=len(data['keys']),native=0,images=len(data['keys']),collapsed=data['collapsed'])


def blue_pencil(data,folder,shape):
    import maya.cmds as c
    if c.about(batch=True):
        raise RuntimeError('Blue Pencil requires the Maya interface; batch mode is not supported')
    camera=(c.listRelatives(shape,parent=True,fullPath=True) or [''])[0].rsplit('|',1)[-1]
    if len(c.ls(camera,long=True))!=1: raise ValueError('Blue Pencil requires a unique camera name')
    if camera!=data['camera']: raise ValueError('Refresh the camera list before sending Blue Pencil drawings')
    c.loadPlugin('bluePencil',quiet=True)
    owner='Cadence_'+data['owner']+'_'
    layer=data['layer_name']
    def names(target=camera):
        if not c.bluePencilNode(exists=True): return []
        return [c.bluePencilLayer(target,queryName=i) for i in range(c.bluePencilLayer(target,count=True))]
    previous=names()
    if layer in previous:
        c.bluePencilUtil(edit=True,ghostPrevious=False)
        c.bluePencilUtil(edit=True,ghostNext=False)
        remove_images(c,image_groups(c,data['owner'],shape))
        return dict(keys=len(data['keys']),native=0,images=len(data['keys']),collapsed=data['collapsed'],blue_pencil=True)
    selection=c.ls(selection=True,long=True) or []; frame=c.currentTime(query=True)
    imported=None
    previous_nodes=set(c.ls(type='bluePencil',long=True) or [])
    c.undoInfo(openChunk=True,chunkName='Cadence Blue Pencil')
    try:
        if data['keys']:
            c.bluePencilFrame(importArchive=(folder/data['archive']).as_posix())
            for node in set(c.ls(type='bluePencil',long=True) or [])-previous_nodes:
                c.addAttr(node,longName='cadenceImported',attributeType='bool',defaultValue=True)
            # Maya imports into the active Blue Pencil camera, ignoring the XML camera name.
            imported=c.bluePencilNode(query=True,camera=True)
            if imported!=camera and layer in names(imported):
                c.bluePencilLayer(imported,move=(names(imported).index(layer),len(names())),newCamera=camera)
            if layer not in names(): raise RuntimeError('Blue Pencil did not import the expected layer')
            # The imported frames already contain Cadence ghosts; native ghosts would duplicate them.
            c.bluePencilUtil(edit=True,ghostPrevious=False)
            c.bluePencilUtil(edit=True,ghostNext=False)
            c.bluePencilNode(refreshGhosting=True)
        for index,name in reversed(list(enumerate(names()))):
            if name in previous and name.startswith(owner): c.bluePencilLayer(camera,delete=index)
        remove_images(c,image_groups(c,data['owner'],shape))
    except BaseException:
        for target in {camera,imported}-{None}:
            for index,name in reversed(list(enumerate(names(target)))):
                if name==layer and (target!=camera or name not in previous): c.bluePencilLayer(target,delete=index)
        raise
    finally:
        c.currentTime(frame,edit=True)
        if selection: c.select([node for node in selection if c.objExists(node)],replace=True)
        else: c.select(clear=True)
        c.undoInfo(closeChunk=True)
    return dict(keys=len(data['keys']),native=0,images=len(data['keys']),collapsed=data['collapsed'],blue_pencil=True)
