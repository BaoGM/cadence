# SPDX-License-Identifier: GPL-3.0-only
import os
import shutil

if __package__:
    from .cadence_runtime import fs_path, fullmatch, TransferCancelled
else:
    from cadence_runtime import fs_path, fullmatch, TransferCancelled


def modes():
    import maya.cmds as c
    return ['blue_pencil', 'images'] if c.about(apiVersion=True) >= 20230000 else ['grease_pencil', 'images']


def blue_loaded(c):
    if 'blue_pencil' not in modes():
        return False
    try:
        return c.pluginInfo('bluePencil', query=True, loaded=True)
    except RuntimeError:
        return False


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
    with open(fs_path(path),'wb') as stream:
        stream.write(header); stream.write(b'\0'*(count*8)); offsets=[]
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
    folder, destination = fs_path(folder), fs_path(destination)
    managed = c.colorManagementPrefs(query=True,cmEnabled=True)
    def copy_pngs():
        space = c.colorManagementFileRules(evaluate=os.path.join(folder, sequence[0]['image'])) if managed else 'Raw'
        for item in sequence:
            shutil.copy2(os.path.join(folder, item['image']), os.path.join(destination, item['image']))
        return [item['image'] for item in sequence], space, [(1., 0.)] * len(sequence)
    if not managed:
        return copy_pngs()
    import ctypes
    import maya.api.OpenMaya as om
    try:
        import numpy as np
        import PyOpenColorIO as ocio
    except ImportError:
        return copy_pngs()
    config_path=os.path.expandvars(c.colorManagementPrefs(query=True,configFilePath=True))
    config_path=config_path.replace('<MAYA_RESOURCES>',os.path.join(fs_path(os.environ['MAYA_LOCATION']), 'resources'))
    config=ocio.Config.CreateFromFile(config_path)
    space=c.colorManagementPrefs(query=True,renderingSpaceName=True)
    transform=ocio.DisplayViewTransform(src=space,
        display=c.colorManagementPrefs(query=True,displayName=True),
        view=c.colorManagementPrefs(query=True,viewName=True),direction=ocio.TRANSFORM_DIR_INVERSE)
    processor=config.getProcessor(transform).getDefaultCPUProcessor()
    names=[]; adjustments=[]
    for item in sequence:
        image=om.MImage(); image.readFromFile(os.path.join(folder,item['image']))
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
        name=os.path.splitext(item['image'])[0]+'.exr'
        # VP2 image-plane textures clamp HDR values; restore their range with colour gain/offset.
        bias=float(min(0.,np.floor(values[:,:,:3].min())))
        gain=float(max(1.,np.ceil(values[:,:,:3].max())-bias))
        values[:,:,:3]=(values[:,:,:3]-bias)/gain
        write_exr(os.path.join(destination,name),values); names.append(name)
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
        if c.attributeQuery('cadenceGrease',node=node,exists=True):
            remove_grease(c,node)
            continue
        members=c.listConnections(node+'.drawings',source=True,destination=False) or []
        for member in members:
            if not c.objExists(member): continue
            children=c.listRelatives(member,children=True,fullPath=True) or []
            marked=c.attributeQuery('cadenceImported',node=member,exists=True)
            planes=[child for child in children if c.nodeType(child)=='imagePlane' and
                (c.attributeQuery('cadenceImported',node=child,exists=True) if marked else
                 fullmatch(r'Cadence_(drawing|ghost)\d*Shape\d*',child.rsplit('|',1)[-1]))]
            if children and len(children)!=len(planes):
                if planes: c.delete(planes)
            else: c.delete(member)
        if c.objExists(node): c.delete(node)


def remove_blue(c,owner,shape):
    if not blue_loaded(c) or not c.bluePencilNode(exists=True): return
    camera=(c.listRelatives(shape,parent=True) or [''])[0]
    prefix='Cadence_'+owner+'_'
    for index in reversed(range(c.bluePencilLayer(camera,count=True))):
        if c.bluePencilLayer(camera,queryName=index).startswith(prefix): c.bluePencilLayer(camera,delete=index)


def prune_blue_node(c,removed=False):
    if not blue_loaded(c) or not c.bluePencilNode(exists=True): return
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
        if blue_loaded(c) and c.bluePencilNode(exists=True):
            for shape in c.ls(type='camera',long=True) or []:
                camera=(c.listRelatives(shape,parent=True) or [''])[0]
                for index in reversed(range(c.bluePencilLayer(camera,count=True))):
                    if fullmatch(r'Cadence_[0-9a-f]{32}_[0-9a-f]{8}',c.bluePencilLayer(camera,queryName=index)):
                        c.bluePencilLayer(camera,delete=index)
                        removed=True
        prune_blue_node(c,removed)
        groups=[node for node in c.ls(type='network',long=True) or []
            if all(c.attributeQuery(attr,node=node,exists=True) for attr in ('cadenceOwner','cadenceCamera','drawings'))
            and fullmatch('[0-9a-f]{32}',c.getAttr(node+'.cadenceOwner') or '')]
        remove_images(c,groups)
    finally:
        c.undoInfo(closeChunk=True)
        c.select([node for node in selection if c.objExists(node)],replace=True) if selection else c.select(clear=True)


def apply(data,folder):
    import maya.cmds as c
    folder = fs_path(folder)
    camera=data['camera']
    if not c.objExists(camera): raise ValueError('Selected camera no longer exists')
    if c.nodeType(camera)=='transform':
        shapes=c.listRelatives(camera,shapes=True,type='camera',fullPath=True) or []
        if not shapes: raise ValueError('Selected object is not a camera')
        camera=shapes[0]
    if c.nodeType(camera)!='camera': raise ValueError('Selected object is not a camera')
    if data['mode']=='grease_pencil': return grease_pencil(data,folder,camera)
    if data['mode']=='blue_pencil': return blue_pencil(data,folder,camera)
    if data['mode']!='images': raise ValueError('Maya supports transparent drawing images')
    owner=data['owner']; selection=c.ls(selection=True,long=True) or []
    project=c.workspace(query=True,rootDirectory=True)
    destination=os.path.join(project,'sourceimages','Cadence',owner,data['revision'])
    if not os.path.isdir(destination): os.makedirs(destination)
    sequence=data.get('sequence',[])
    if data['keys'] and not sequence: raise ValueError('Update Cadence before transferring images')
    filenames,color_space,adjustments=prepare_images(c,sequence,folder,destination)
    # Maya 2022 VP2 misresolves zero-padded sequences whose initial number is all zeros.
    numbered=[]
    for index,name in enumerate(filenames):
        target='drawing.%d%s'%(100001+index,os.path.splitext(name)[1])
        shutil.copy2(os.path.join(destination,name),os.path.join(destination,target))
        os.remove(os.path.join(destination,name))
        numbered.append(target)
    filenames=numbered
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
            transform,shape=c.imagePlane(camera=camera,fileName=os.path.join(destination,filenames[0]).replace('\\','/'),name='Cadence_drawing',showInAllViews=False)
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
                c.setKeyframe(shape,attribute='frameExtension',time=item['frame'],value=100001+index,inTangentType='flat',outTangentType='step')
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


def grease_path(c,node):
    path=(c.ls(node,long=True) or [node])[0]
    return path.rsplit('|',1)[-1] if '->' in path else path


def node_ids(c):
    # Maya ignores uuid=True when ls receives no explicit objects.
    return set(c.ls(c.ls(long=True),uuid=True) or [])


def delete_grease_plane(c,plane):
    uid=c.ls(plane,uuid=True)[0]
    c.imagePlane(plane,edit=True,detach=True)
    nodes=c.ls(uid,long=True)
    if nodes: c.delete(nodes)


def remove_grease(c,group):
    members=[grease_path(c,n) for n in c.listConnections(group+'.drawings',source=True,destination=False,shapes=True) or []]
    owned=set(members)
    for node in members:
        if c.objExists(node) and c.nodeType(node)=='greasePencilSequence':
            for plane in c.listConnections(node+'.message',type='greasePlane',shapes=True) or []:
                delete_grease_plane(c,plane)
    for node in members:
        if not c.objExists(node): continue
        if c.nodeType(node)=='transform':
            children=c.listRelatives(node,children=True,fullPath=True) or []
            if any(child not in owned for child in children): continue
        c.delete(node)
    if c.objExists(group): c.delete(group)


def apply_steps(data,folder):
    if data['mode']!='grease_pencil':
        yield dict(result=apply(data,folder)); return
    import maya.cmds as c
    shape=data['camera']
    if not c.objExists(shape): raise ValueError('Selected camera no longer exists')
    if c.nodeType(shape)=='transform':
        shapes=c.listRelatives(shape,shapes=True,type='camera',fullPath=True) or []
        if not shapes: raise ValueError('Selected object is not a camera')
        shape=shapes[0]
    if c.nodeType(shape)!='camera': raise ValueError('Selected object is not a camera')
    for update in grease_pencil_steps(data,fs_path(folder),shape): yield update


def grease_pencil(data,folder,shape):
    result=None
    for update in grease_pencil_steps(data,folder,shape):
        if 'result' in update: result=update['result']
    return result


def grease_pencil_steps(data,folder,shape):
    import maya.cmds as c
    import maya.mel as mel
    from PySide2 import QtCore,QtWidgets
    class Progress(QtWidgets.QDialog):
        cancelled=False
        def reject(self): self.cancelled=True
    progress_dialog=Progress()
    progress_dialog.setWindowTitle('Cadence - Grease Pencil')
    progress_dialog.setWindowModality(QtCore.Qt.ApplicationModal)
    progress_dialog.setWindowFlag(QtCore.Qt.WindowCloseButtonHint,False)
    progress_bar=QtWidgets.QProgressBar()
    progress_layout=QtWidgets.QVBoxLayout(progress_dialog)
    progress_layout.addWidget(progress_bar)
    progress_dialog.setMinimumWidth(320)
    if 'grease_pencil' not in modes() or c.about(batch=True):
        raise RuntimeError('Grease Pencil requires the Maya 2022 interface')
    panels=c.getPanel(type='modelPanel') or []
    panel=c.getPanel(withFocus=True)
    focus=panel
    if panel not in panels:
        visible=c.getPanel(visiblePanels=True) or []
        panel=next((p for p in panels if p in visible),None)
    if not panel: raise RuntimeError('Open a Maya camera viewport before sending drawings')
    owner=data['owner']; old=image_groups(c,owner,shape)
    old_members=set(grease_path(c,n) for group in old for n in (c.listConnections(group+'.drawings',source=True,destination=False,shapes=True) or []))
    for plane in c.listConnections(shape+'.imagePlane',source=True,destination=False,shapes=True) or []:
        if c.nodeType(plane)=='greasePlane':
            native=c.listConnections(plane+'.greaseSequence',source=True,destination=False) or []
            if not native or any(grease_path(c,n) not in old_members for n in native):
                raise ValueError('This camera already has Grease Pencil drawings. Choose another camera to preserve them.')
    sequence=data.get('sequence',[])
    if data['keys'] and not sequence: raise ValueError('Update Cadence before transferring drawings')
    destination=os.path.join(c.workspace(query=True,rootDirectory=True),'sourceimages','Cadence',owner,data['revision'])
    if not os.path.isdir(destination): os.makedirs(destination)
    selection=c.ls(selection=True,long=True) or []; frame=c.currentTime(query=True)
    tool=c.currentCtx(); previous_camera=c.modelPanel(panel,query=True,camera=True)
    before=node_ids(c); created=[]; temporary=None; texture_size=None
    suspended=False
    c.undoInfo(openChunk=True,chunkName='Cadence Grease Pencil')
    progress_dialog.show()
    try:
        for index,item in enumerate(sequence):
            yield dict(progress=int(10.*index/max(1,len(sequence))))
            if progress_dialog.cancelled: raise TransferCancelled()
            shutil.copy2(os.path.join(folder,item['image']),os.path.join(destination,item['image']))
        if sequence:
            temporary,temp_shape=c.camera(name='Cadence_transfer_camera')
            for attr in ('orthographic','orthographicWidth','focalLength','horizontalFilmAperture','verticalFilmAperture','filmFit'):
                c.setAttr(temp_shape+'.'+attr,c.getAttr(shape+'.'+attr))
            c.setFocus(panel); c.lookThru(panel,temporary)
            c.select(clear=True)
            mel.eval('source greasePencilContext;')
            c.setToolTo('selectSuperContext'); c.setToolTo('greasePencilSuperContext'); c.refresh(force=True)
            texture_size=c.greasePencilCtx('greasePencilContext',query=True,fileTextureSize=True)
            # Blank placeholders are replaced by full-resolution Cadence images below.
            c.greasePencilCtx('greasePencilContext',edit=True,fileTextureSize=64)
            textures=[]; known=set()
            c.refresh(suspend=True)
            for ordinal,item in enumerate(sequence):
                progress=10+int(80.*ordinal/max(1,len(sequence)))
                progress_bar.setValue(progress)
                yield dict(progress=progress)
                if progress_dialog.cancelled: raise TransferCancelled()
                c.currentTime(item['frame'],edit=True,update=False)
                c.greasePencilCtx('greasePencilContext',edit=True,createOrEditFrame=item['frame'])
                native=c.greasePencilCtx('greasePencilContext',query=True,sequenceNodeName=True)
                indices=c.getAttr(native+'.frame',multiIndices=True) or []
                added=set(indices)-known
                index=next(iter(added)) if len(added)==1 else next(i for i in indices if c.getAttr(native+'.frame[%d].frameTime'%i)==item['frame'])
                known=set(indices)
                plugs=c.listConnections(native+'.frame[%d].frameEnable'%index,source=False,destination=True,plugs=True) or []
                texture=next(p.rsplit('.',1)[0]+'.color' for p in plugs if c.nodeType(p.split('.')[0])=='layeredTexture')
                files=c.listConnections(texture,source=True,destination=False,type='file') or []
                if len(files)!=1: raise RuntimeError('Maya did not create a Grease Pencil frame texture')
                textures.append((files[0],item['image']))
            c.setToolTo('selectSuperContext')
            c.greasePencilCtx('greasePencilContext',edit=True,fileTextureSize=texture_size)
            c.refresh(suspend=suspended)
            yield dict(progress=92)
            if progress_dialog.cancelled: raise TransferCancelled()
            for index,(texture,filename) in enumerate(textures):
                if index%16==0:
                    yield dict(progress=92+int(4.*index/max(1,len(textures))))
                    if progress_dialog.cancelled: raise TransferCancelled()
                c.setAttr(texture+'.fileTextureName',os.path.join(destination,filename).replace('\\','/'),type='string')
            native=c.greasePencilCtx('greasePencilContext',query=True,sequenceNodeName=True)
            if not native: raise RuntimeError('Maya did not create a Grease Pencil sequence')
            actual=sorted(c.getAttr(native+'.frame[%d].frameTime'%i) for i in c.getAttr(native+'.frame',multiIndices=True) or [])
            if actual!=[item['frame'] for item in sequence]: raise RuntimeError('Incomplete Grease Pencil import')
            planes=c.listConnections(native+'.message',type='greasePlane',shapes=True) or []
            if len(planes)!=1: raise RuntimeError('Maya did not create the Grease Pencil camera plane')
            c.setAttr(native+'.preGhost',False); c.setAttr(native+'.postGhost',False)
            plane_id=c.ls(planes[0],uuid=True)[0]
            c.imagePlane(planes[0],edit=True,camera=shape)
            if not c.ls(plane_id): raise RuntimeError('Grease Pencil camera attachment failed')
            plane=c.ls(plane_id)[0]
            aperture=c.getAttr(shape+'.horizontalFilmAperture')
            c.setAttr(plane+'.fit',4)
            c.setAttr(plane+'.sizeX',aperture)
            c.setAttr(plane+'.sizeY',aperture*data['height']/float(data['width']))
            # Maya drives square render/paint meshes independently of the image-plane bounds.
            for attribute,output in (('renderPlane','renderPlaneScale'),('sourcePlane','sourcePlaneScale')):
                for transform in c.listConnections(plane+'.'+attribute,source=True,destination=False) or []:
                    correction=c.createNode('multiplyDivide',name='Cadence_drawing_aspect')
                    c.connectAttr(plane+'.'+output,correction+'.input1')
                    c.setAttr(correction+'.input2',1.,1.,data['height']/float(data['width']),type='double3')
                    c.connectAttr(correction+'.output',transform+'.scale',force=True)
            c.lookThru(panel,shape)
            c.setToolTo('greasePencilSuperContext'); c.refresh(force=True)
            c.setToolTo('selectSuperContext')
            c.lookThru(panel,previous_camera)
            c.delete(temporary); temporary=None
        created=[grease_path(c,node) for uid in node_ids(c)-before for node in c.ls(uid,long=True)
                 if not ('->' in node or c.nodeType(node)=='greasePlane')]
        group=c.createNode('network',name='Cadence_grease_pencil')
        created.append(group)
        for name,value in (('cadenceOwner',owner),('cadenceCamera',shape)):
            c.addAttr(group,longName=name,dataType='string'); c.setAttr(group+'.'+name,value,type='string')
        c.addAttr(group,longName='cadenceGrease',attributeType='bool',defaultValue=True)
        c.addAttr(group,longName='drawings',attributeType='message',multi=True)
        for index,node in enumerate(created[:-1]):
            if index%64==0:
                yield dict(progress=97)
                if progress_dialog.cancelled: raise TransferCancelled()
            if not c.objExists(node): continue
            try:
                c.addAttr(node,longName='cadenceImported',attributeType='bool',defaultValue=True)
                c.connectAttr(node+'.message',group+'.drawings[%d]'%index)
            except RuntimeError as error:
                raise RuntimeError('Grease Pencil ownership failed for '+node+': '+str(error))
        yield dict(progress=98)
        if progress_dialog.cancelled: raise TransferCancelled()
        remove_images(c,old)
    except BaseException:
        c.setToolTo('selectSuperContext')
        c.lookThru(panel,previous_camera)
        for native in c.ls(type='greasePencilSequence') or []:
            if c.ls(native,uuid=True)[0] not in before:
                for plane in c.listConnections(native+'.message',type='greasePlane',shapes=True) or []:
                    delete_grease_plane(c,plane)
        for uid in node_ids(c)-before:
            nodes=[node for node in c.ls(uid,long=True) if '->' not in node]
            if nodes: c.delete(nodes)
        raise
    finally:
        c.refresh(suspend=suspended)
        if texture_size is not None: c.greasePencilCtx('greasePencilContext',edit=True,fileTextureSize=texture_size)
        progress_dialog.done(0); progress_dialog.deleteLater()
        c.lookThru(panel,previous_camera)
        c.setToolTo(tool)
        c.currentTime(frame,edit=True)
        c.select([node for node in selection if c.objExists(node)],replace=True) if selection else c.select(clear=True)
        if focus and c.getPanel(typeOf=focus)=='modelPanel': c.setFocus(focus)
        c.undoInfo(closeChunk=True)
    yield dict(result=dict(keys=len(data['keys']),native=0,images=len(data['keys']),collapsed=data['collapsed'],grease_pencil=True))


def blue_pencil(data,folder,shape):
    import maya.cmds as c
    if 'blue_pencil' not in modes():
        raise RuntimeError('This Maya version supports transparent drawing images')
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
            c.bluePencilFrame(importArchive=os.path.join(fs_path(folder),data['archive']).replace('\\','/'))
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
