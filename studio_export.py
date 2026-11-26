# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import dataclass
from pathlib import Path
import os
import tempfile


@dataclass(frozen=True)
class StudioFormat:
    label: str
    extension: str
    pixels: str
    options: tuple
    sequence: bool = False
    alpha: bool = False


PROFILES = {
    'png': StudioFormat('Séquence PNG RGBA (*.png)', '.png', 'rgba', ('-c:v', 'png'), True, True),
    'prores-hq': StudioFormat('MOV ProRes 422 HQ (*.mov)', '.mov', 'yuv422p10le',
                              ('-c:v', 'prores_ks', '-profile:v', 'hq')),
    'prores-4444': StudioFormat('MOV ProRes 4444 (*.mov)', '.mov', 'yuva444p10le',
                                ('-c:v', 'prores_ks', '-profile:v', '4444', '-alpha_bits', '16'), alpha=True),
    'exr': StudioFormat('Séquence OpenEXR RGBA (*.exr)', '.exr', 'gbrapf32le',
                        ('-c:v', 'exr', '-format', 'half', '-compression', 'zip16'), True, True),
    'tga': StudioFormat('Séquence Targa RGBA (*.tga)', '.tga', 'bgra', ('-c:v', 'targa', '-rle', '1'), True, True),
    'dnxhr': StudioFormat('MOV DNxHR HQ (*.mov)', '.mov', 'yuv422p', ('-c:v', 'dnxhd', '-profile:v', 'dnxhr_hq')),
}


def selected_profile(key, extension):
    if key is None:
        return next((p for p in PROFILES.values() if p.sequence and p.extension == extension), None)
    profile = PROFILES.get(key)
    if profile is None or profile.extension != extension:
        raise ValueError('Le format sélectionné et l’extension du fichier doivent correspondre.')
    return profile


def output_filter(profile):
    if profile.extension == '.exr':
        # The viewer works in display-referred sRGB. EXR stores associated linear RGB.
        linear = 'if(lte(val/maxval,0.04045),val/12.92,maxval*pow((val/maxval+0.055)/1.055,2.4))'
        return (f"format=gbrap16le,lutrgb=r='{linear}':g='{linear}':b='{linear}',"
                'premultiply=inplace=1:planes=7,format=gbrapf32le')
    if not profile.sequence:
        pad = '' if profile.alpha else 'pad=ceil(iw/2)*2:ih,'
        return pad + 'scale=out_color_matrix=bt709:out_range=tv,format=' + profile.pixels
    return 'format=' + profile.pixels


def sequence_folder(output):
    return output.with_name(output.stem + '-' + output.suffix[1:].lower())


def write_sequence(profile, output, start, length, encode, cancel):
    from media import Cancelled
    if not 0 <= start <= 2_147_483_647 - length:
        raise ValueError('Numéro de première image hors limites.')
    target = sequence_folder(output)
    if os.path.lexists(target):
        raise ValueError('Le dossier de séquence existe déjà. Choisissez un autre nom.')
    digits = max(4, len(str(start + length - 1)))
    with tempfile.TemporaryDirectory(prefix='.cadence-frames-', dir=output.parent) as temp:
        folder = Path(temp) / 'frames'
        folder.mkdir()
        # Escape the whole path too: a user-selected parent directory may contain "%".
        pattern = str(folder / (output.stem + '.')).replace('%', '%%') + f'%0{digits}d' + profile.extension
        encode(['-start_number', str(start), '-f', 'image2', pattern])
        for number in range(start, start + length):
            if cancel and cancel.is_set():
                raise Cancelled()
            if not (folder / f'{output.stem}.{number:0{digits}d}{profile.extension}').is_file():
                raise RuntimeError('La séquence exportée est incomplète.')
        if os.path.lexists(target):
            raise ValueError('Le dossier de séquence existe déjà. Choisissez un autre nom.')
        folder.rename(target)
    return target / f'{output.stem}.{start:0{digits}d}{profile.extension}'
