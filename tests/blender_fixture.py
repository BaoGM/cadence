# SPDX-License-Identifier: GPL-3.0-only
import json
import os
from pathlib import Path
import sys
import traceback

import bpy

root = Path(os.environ['CADENCE_BLENDER_TEST'])
scene = bpy.context.scene
scene.frame_start = 101
scene.frame_end = 400
scene.render.fps = 24
scene.frame_set(101)
scene.objects['Cube']['cadence_test_sentinel'] = True
sequence = None


def tick():
    global sequence
    request = root / 'request.json'
    try:
        data = json.loads(request.read_text())
        if data['id'] == sequence:
            return .05
        sequence = data['id']
        action = data['action']
        if action == 'frame':
            scene.frame_set(data['frame'])
        elif action == 'rate':
            scene.render.fps = data['fps']
            scene.render.fps_base = data.get('base', 1.)
        elif action == 'save':
            bpy.ops.wm.save_as_mainfile(filepath=str(root / 'transferred.blend'))
        elif action == 'quit':
            bpy.ops.wm.quit_blender()
            return None
        objects = [obj for obj in scene.objects if obj.get('cadence_owner')]
        result = dict(id=sequence, ok=True, version=bpy.app.version_string,
            frame=scene.frame_current + scene.frame_subframe,
            autostart='cadence_autostart' in sys.modules,
            objects=[dict(name=obj.name, type=obj.type, parent=obj.parent.name if obj.parent else None) for obj in objects],
            grease_pencil_frames=sum(len(layer.frames) for obj in objects if obj.type == 'GREASEPENCIL' for layer in obj.data.layers),
            packed_images=sum(bool(image.packed_file) for image in bpy.data.images if image.get('cadence_owner')),
            sentinel=bool(scene.objects.get('Cube') and scene.objects['Cube'].get('cadence_test_sentinel')))
        (root / 'response.json').write_text(json.dumps(result))
    except FileNotFoundError:
        pass
    except Exception:
        (root / 'response.json').write_text(json.dumps(dict(id=sequence, ok=False, error=traceback.format_exc())))
    return .05


bpy.app.timers.register(tick, first_interval=.1, persistent=True)
