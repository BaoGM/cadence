# SPDX-License-Identifier: GPL-3.0-only
import logging
import os


def open_preview(path,disabled=False,share_delete=False):
    from media_inputs import open_local_media
    def open_input(**options):
        if not share_delete or os.name!='nt':
            return open_local_media(path,**options)
        from export_sources import open_shared
        stream=open_shared(path)
        try:
            return open_local_media(stream,buffer_size=256*1024,**options)
        except BaseException:
            stream.close()
            raise
    mode=os.environ.get('CADENCE_HW_DECODE','off').lower()
    devices=('d3d11va','cuda') if mode=='auto' else (mode,) if mode in ('d3d11va','cuda','dxva2') else ()
    if not disabled and devices:
        from av.codec.hwaccel import HWAccel,hwdevices_available
        available=hwdevices_available()
        for device in devices:
            if device not in available: continue
            container=None
            try:
                container=open_input(hwaccel=HWAccel(device,allow_software_fallback=True))
                if container.streams.video and container.streams.video[0].codec_context.is_hwaccel:
                    logging.info('Preview hardware decoder %s: %s',device,path)
                    return container,True
            except Exception:
                logging.warning('Hardware decoder %s unavailable for %s; trying fallback',device,path,exc_info=True)
            if container is not None: container.close()
        logging.info('Preview software decoder fallback: %s',path)
    return open_input(),False
