# SPDX-License-Identifier: GPL-3.0-only
from studio_icons import icon


def tool_icon(tool):
    name = {'brush': 'pen', 'eraser': 'erase'}.get(tool, tool)
    return icon(name)
