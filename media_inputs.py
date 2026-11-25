# SPDX-License-Identifier: GPL-3.0-only
LOCAL_PROTOCOLS = 'file'


def open_local_media(source, **kwargs):
    import av
    return av.open(source, options={'protocol_whitelist': LOCAL_PROTOCOLS}, **kwargs)


def local_input_args(args):
    result = []
    for arg in args:
        if arg == '-i':
            result.extend(('-protocol_whitelist', LOCAL_PROTOCOLS))
        result.append(arg)
    return result
