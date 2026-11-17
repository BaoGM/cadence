# SPDX-License-Identifier: GPL-3.0-only
from clip_geometry import geometry_filter,IDENTITY
from cadence_change import video_filter


def video_graph(state,media,sources,fps,width,height,apply_exposure):
    from media import exposure_filter
    filters=[]; segments=[segment for track in state.tracks for segment in track.segments]
    for index,key in enumerate(sources):
        uses=[i for i,segment in enumerate(segments) if segment.media==key and not segment.muted]
        base=f'[{index}:v:0]'+video_filter(fps,media[key].get('cadence'))
        base+=f',format=rgba,scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black@0,setsar=1'
        if len(uses)>1: base+=f',split={len(uses)}'
        filters.append(base+''.join(f'[src{i}]' for i in uses))
    offset=0
    for track_index,track in enumerate(state.tracks):
        labels=[]
        for index,segment in enumerate(track.segments,offset):
            label=f'v{index}'; labels.append(label)
            if segment.media not in sources or segment.muted:
                filters.append(f'color=c=black@0:s={width}x{height}:r={fps},format=rgba,trim=end_frame={segment.length},setpts=PTS-STARTPTS[{label}]')
            else:
                geometry=''
                if segment.crop!=IDENTITY or segment.placement!=IDENTITY or segment.rotation:
                    geometry=','+geometry_filter(segment,width,height).replace('format=rgb24','format=rgba').replace(':black',':black@0').replace('c=black,','c=black@0,')
                filters.append(f'[src{index}]trim=start_frame={segment.start}:end_frame={segment.end},setpts=PTS-STARTPTS'+geometry+f'[{label}]')
        offset+=len(track.segments)
        if track.length<state.length:
            label=f'tail{track_index}'; labels.append(label)
            filters.append(f'color=c=black@0:s={width}x{height}:r={fps},format=rgba,trim=end_frame={state.length-track.length},setpts=PTS-STARTPTS[{label}]')
        joined=f'joined{track_index}'
        filters.append(''.join(f'[{label}]' for label in labels)+f'concat=n={len(labels)}:v=1:a=0[{joined}]')
        effect=exposure_filter(track.exposure)+',' if apply_exposure and track.exposure else ''
        if track.flip_h: effect+='hflip,'
        if track.flip_v: effect+='vflip,'
        filters.append(f'[{joined}]'+effect+f'format=rgba[track{track_index}]')
    filters.append(f'color=c=black:s={width}x{height}:r={fps},format=rgba,trim=end_frame={state.length},setpts=PTS-STARTPTS[background]')
    previous='background'
    for index in reversed(range(len(state.tracks))):
        label='drawbase' if index==0 else f'layer{index}'
        filters.append(f'[{previous}][track{index}]overlay=shortest=1:format=auto[{label}]')
        previous=label
    return filters
