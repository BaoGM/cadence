# SPDX-License-Identifier: GPL-3.0-only
from types import SimpleNamespace

from integrations.cadence_bridge import Bridge
from test_sync1120 import application, link, pump


def test_multiple_hosts_selection_reconnection_and_drawing_routing(link, application):
    hosts = [dict(frame=1., start=1., end=300., fps=24.,
                  instance=dict(application='Blender', scene=name, pid=i + 100))
             for i, name in enumerate(('First', 'Second'))]
    applied = [[], []]
    commands = [[], []]
    bridges = []
    for i, state in enumerate(hosts):
        def set_frame(frame, index=i):
            hosts[index]['frame'] = frame; applied[index].append(frame)
        bridge = Bridge('blender', lambda state=state: dict(state), set_frame)
        def execute(host, message, root, index=i):
            commands[index].append(message['type'])
            return dict(type='drawing_cameras', cameras=['Camera' + str(index)])
        bridge.drawings = SimpleNamespace(execute=execute)
        bridges.append(bridge)
    def wait(predicate):
        pump(application, lambda: ([b.tick() for b in bridges], predicate())[1])
    try:
        wait(lambda: len(link.instances()) == 2 and link.metadata and link.cameras)
        assert link.select_instance(bridges[0].instance_id)
        wait(lambda: link.cameras == ['Camera0'])
        hosts[1]['frame'] = 99
        hosts[0]['frame'] = 31
        wait(lambda: link.window.doc.state.position == 30)
        link.window.seek(70)
        wait(lambda: hosts[0]['frame'] == 71)
        assert hosts[1]['frame'] == 99 and not applied[1]
        assert link.select_instance(bridges[1].instance_id)
        wait(lambda: link.window.doc.state.position == 98 and link.cameras == ['Camera1'])
        link.window.seek(80)
        wait(lambda: hosts[1]['frame'] == 81)
        assert hosts[0]['frame'] == 71
        link.drawing_request = 'test-transfer'
        assert not link.select_instance(bridges[0].instance_id)
        link.drawing_request = None
        bridges[1].disconnect(); bridges[1].next_connect = float('inf')
        wait(lambda: link.peer is None and len(link.instances()) == 1)
        hosts[0]['frame'] = 155
        for _ in range(20):
            bridges[0].tick(); application.processEvents()
        assert link.window.doc.state.position == 80
        bridges[1].next_connect = 0
        wait(lambda: link.peer is not None and len(link.instances()) == 2 and
             any('Second' in label for identity, label in link.instances() if identity == bridges[1].instance_id))
        assert link.selected_instance == bridges[1].instance_id
        assert all('Second' in label for identity, label in link.instances() if identity == bridges[1].instance_id)
    finally:
        for bridge in bridges: bridge.close()
