# SPDX-License-Identifier: GPL-3.0-only
def cameras():
    import bpy
    return [obj.name for obj in bpy.context.scene.objects if obj.type=='CAMERA'][:64]


def linear(value):
    return value/12.92 if value<=.04045 else ((value+.055)/1.055)**2.4


def remove_collections(bpy,collections,owner):
    if collections: bpy.context.view_layer.update()
    for collection in collections:
        for obj in list(collection.objects):
            if obj.get('cadence_owner')==owner:
                for child in obj.children:
                    if child.get('cadence_owner')!=owner:
                        matrix=child.matrix_world.copy(); child.parent=None; child.matrix_world=matrix
                bpy.data.objects.remove(obj,do_unlink=True)
            elif obj.name not in bpy.context.scene.collection.objects:
                bpy.context.scene.collection.objects.link(obj)
        for child in list(collection.children):
            if child.name not in bpy.context.scene.collection.children:
                bpy.context.scene.collection.children.link(child)
        bpy.data.collections.remove(collection)


def prune_resources(bpy,owner):
    for library in (bpy.data.meshes,bpy.data.grease_pencils,bpy.data.materials,bpy.data.images,bpy.data.actions):
        for block in list(library):
            if block.get('cadence_owner')==owner and block.users==0: library.remove(block)


def clear():
    import bpy
    import re
    if bpy.app.is_job_running('RENDER'): raise RuntimeError('Wait for the current render to finish')
    collections=[collection for collection in bpy.data.collections
        if isinstance(collection.get('cadence_owner'),str) and re.fullmatch('[0-9a-f]{32}',collection['cadence_owner'])
        and 'cadence_camera' in collection]
    owners={collection['cadence_owner'] for collection in collections}
    for owner in owners:
        remove_collections(bpy,[collection for collection in bpy.data.collections
            if collection.get('cadence_owner')==owner and 'cadence_camera' in collection],owner)
        prune_resources(bpy,owner)


def apply(data, folder):
    import bpy
    scene=bpy.context.scene
    camera=scene.objects.get(data['camera'])
    if camera is None or camera.type!='CAMERA': raise ValueError('Selected camera no longer exists')
    if bpy.app.is_job_running('RENDER'): raise RuntimeError('Wait for the current render to finish')
    if data['mode']=='native' and bpy.app.version<(4,3,0):
        raise RuntimeError('Grease Pencil transfer requires Blender 4.3 or later; choose transparent images')
    owner=data['owner']
    old=[c for c in bpy.data.collections if c.get('cadence_owner')==owner and c.get('cadence_camera')==camera.name]
    distance=max(camera.data.clip_start*2,1.)
    if distance>=camera.data.clip_end: raise ValueError('Camera clipping range is too small')
    collection=bpy.data.collections.new('Cadence - '+owner[:8])
    collection['cadence_owner']=owner; collection['cadence_camera']=camera.name
    scene.collection.children.link(collection)
    created=[]; resources=[]
    corners=camera.data.view_frame(scene=scene)
    projected=[v if camera.data.type=='ORTHO' else v*(distance/abs(v.z)) for v in corners]
    left,right=min(v.x for v in projected),max(v.x for v in projected)
    bottom,top=min(v.y for v in projected),max(v.y for v in projected)
    aspect=data['width']/data['height']
    height=min(top-bottom,(right-left)/aspect); width=height*aspect
    cx,cy=(left+right)/2,(top+bottom)/2

    def position(x,y,z): return (cx+(x-.5)*width,cy+(.5-y)*height,z)
    def object_for(name,block):
        obj=bpy.data.objects.new(name,block); collection.objects.link(obj)
        obj['cadence_owner']=owner; obj.parent=camera
        created.append(obj); return obj
    def prune():
        prune_resources(bpy,owner)
    def animate(target,path,values):
        for frame,value in values:
            setattr(target,path,value); target.keyframe_insert(data_path=path,frame=frame)
        action=target.id_data.animation_data.action if target.id_data.animation_data else None
        if action:
            action['cadence_owner']=owner
            for layer in action.layers:
                for strip in layer.strips:
                    for bag in strip.channelbags:
                        for curve in bag.fcurves:
                            for point in curve.keyframe_points: point.interpolation='CONSTANT'
    images={}
    def plane(key,ghost=False):
        mesh=bpy.data.meshes.new('Cadence image'); resources.append((bpy.data.meshes,mesh))
        z=-distance*(1.001 if ghost else 1.)
        coords=[position(0,1,z),position(1,1,z),position(1,0,z),position(0,0,z)]
        mesh.from_pydata(coords,[],[(0,1,2,3)])
        uv=mesh.uv_layers.new()
        for loop,point in zip(uv.data,[(0,0),(1,0),(1,1),(0,1)]): loop.uv=point
        obj=object_for('Cadence pelure' if ghost else 'Cadence dessin',mesh)
        material=bpy.data.materials.new('Cadence image'); resources.append((bpy.data.materials,material))
        material.use_nodes=True
        material.surface_render_method='BLENDED'
        nodes=material.node_tree.nodes; nodes.clear(); links=material.node_tree.links
        tex=nodes.new('ShaderNodeTexImage')
        image=images.get(key['image'])
        if image is None:
            image=bpy.data.images.load(str(folder/key['image']),check_existing=False)
            resources.append((bpy.data.images,image)); image.pack(); images[key['image']]=image
        tex.image=image
        emission=nodes.new('ShaderNodeEmission'); links.new(tex.outputs['Color'],emission.inputs['Color'])
        transparent=nodes.new('ShaderNodeBsdfTransparent')
        alpha=nodes.new('ShaderNodeMath'); alpha.operation='MULTIPLY'; links.new(tex.outputs['Alpha'],alpha.inputs[0])
        mix=nodes.new('ShaderNodeMixShader'); links.new(alpha.outputs[0],mix.inputs[0]); links.new(transparent.outputs[0],mix.inputs[1]); links.new(emission.outputs[0],mix.inputs[2])
        output=nodes.new('ShaderNodeOutputMaterial'); links.new(mix.outputs[0],output.inputs[0])
        mesh.materials.append(material)
        start,end=key['start'],key['end']
        values=[(f,0. if start<=f<end else a) for f,a in key['envelope']] if ghost else [(start-1,0.),(start,1.),(end-1,1.),(end,0.)]
        for frame,value in dict(values).items():
            alpha.inputs[1].default_value=value
            alpha.inputs[1].keyframe_insert(data_path='default_value',frame=frame)
        animate(obj,'hide_render',[(f,a==0) for f,a in values])
        obj.hide_viewport=True
        # Image empties disappear when viewport overlays are disabled.
        if bpy.app.version>=(4,3,0):
            gp=bpy.data.grease_pencils.new('Cadence image'); resources.append((bpy.data.grease_pencils,gp))
            display=object_for('Cadence pelure' if ghost else 'Cadence image',gp)
            display.hide_render=True; display.hide_select=True
            layer=gp.layers.new('Cadence',set_active=True); layer.use_lights=False; layer.use_onion_skinning=False
            fill=bpy.data.materials.new('Cadence image texture'); resources.append((bpy.data.materials,fill))
            bpy.data.materials.create_gpencil_data(fill); gp.materials.append(fill)
            style=fill.grease_pencil; style.fill_style='TEXTURE'; style.fill_image=image
            style.fill_color=(1.,1.,1.,1.); style.mix_factor=0.; style.texture_clamp=True
            style.texture_scale=(1.,1.); style.texture_offset=(-.5,-.5)
            if bpy.app.version<(5,1,0): style.show_fill=True; style.show_stroke=False
            drawing=layer.frames.new(min(f for f,a in values)).drawing; drawing.add_strokes([4])
            stroke=drawing.strokes[0]; stroke.cyclic=True
            if hasattr(stroke,'fill_id'): stroke.fill_id=1; stroke.hide_stroke=True
            for point,co in zip(stroke.points,coords):
                point.position=co; point.radius=0.; point.opacity=1.
            drawing.attributes.new('uv_scale','FLOAT2','CURVE').data[0].vector=(width,height)
            animate(layer,'opacity',values)
            animate(display,'hide_viewport',[(f,a==0) for f,a in values])
        else:
            display=object_for('Cadence pelure' if ghost else 'Cadence image',None)
            display.empty_display_type='IMAGE'; display.data=image
            display.empty_display_size=max(width,height); display.location=(cx,cy,z)
            display.empty_image_side='DOUBLE_SIDED'; display.use_empty_image_alpha=True
            display.show_empty_image_perspective=True; display.show_empty_image_orthographic=True
            display.hide_select=True
            animate(display,'color',[(f,(1.,1.,1.,a)) for f,a in values])
            animate(display,'hide_viewport',[(f,a==0) for f,a in values])
        action=material.node_tree.animation_data.action
        action['cadence_owner']=owner
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for point in curve.keyframe_points: point.interpolation='CONSTANT'

    native_count=0
    try:
        compatible=[key for key in data['keys'] if key['strokes'] is not None and data['mode']=='native']
        if compatible:
            gp=bpy.data.grease_pencils.new('Cadence drawings'); resources.append((bpy.data.grease_pencils,gp))
            obj=object_for('Cadence - Grease Pencil',gp)
            layer=gp.layers.new('Cadence',set_active=True); layer.use_lights=False; layer.use_onion_skinning=False
            materials={}
            frames={key['end']:None for key in compatible}; frames.update({key['start']:key for key in compatible})
            for time,key in sorted(frames.items()):
                drawing=layer.frames.new(time).drawing
                if key is None: continue
                native_count+=1
                strokes=key['strokes']; drawing.add_strokes([max(2,len(s['points'])) for s in strokes]) if strokes else None
                for stroke,source in zip(drawing.strokes,strokes):
                    stroke.cyclic=source['cyclic']
                    rgba=source['color']; color=tuple(linear(v) for v in rgba[:3])+(1.,)
                    if color not in materials:
                        material=bpy.data.materials.new('Cadence stroke'); resources.append((bpy.data.materials,material))
                        bpy.data.materials.create_gpencil_data(material); material.grease_pencil.color=color
                        material.diffuse_color=color
                        materials[color]=len(gp.materials); gp.materials.append(material)
                    stroke.material_index=materials[color]
                    points=source['points'] if len(source['points'])>1 else source['points']*2
                    for point,(x,y,radius) in zip(stroke.points,points):
                        point.position=position(x,y,-distance); point.radius=radius*height
                        point.opacity=rgba[3]; point.vertex_color=(0.,0.,0.,0.)
        for key in data['keys']:
            if key['strokes'] is None or data['mode']=='images': plane(key)
            if any(alpha>0 and not key['start']<=frame<key['end'] for frame,alpha in key['envelope']): plane(key,True)
        remove_collections(bpy,old,owner)
        for library,resource in resources: resource['cadence_owner']=owner
        prune()
        scene.frame_set(scene.frame_current,subframe=scene.frame_subframe)
        if images and bpy.app.version>=(4,3,0):
            # Solid's Material mode replaces image fills with an opaque colour.
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type=='VIEW_3D' and area.spaces.active.shading.type=='SOLID':
                        area.spaces.active.shading.color_type='TEXTURE'
    except BaseException:
        for library,resource in resources: resource['cadence_owner']=owner
        for obj in created:
            if obj.name in bpy.data.objects: bpy.data.objects.remove(obj,do_unlink=True)
        bpy.data.collections.remove(collection)
        prune()
        raise
    return dict(keys=len(data['keys']),native=native_count,images=len(data['keys'])-native_count,collapsed=data['collapsed'])
