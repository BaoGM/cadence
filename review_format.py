# SPDX-License-Identifier: GPL-3.0-only
import re

BOXES = ('☐', '☑')


def text_units(text):
    # QTextCursor counts UTF-16 code units, including for non-BMP characters.
    return len(text.encode('utf-16-le', errors='surrogatepass')) // 2


def box_positions(text):
    previous = offset = 0
    for match in re.finditer('[☐☑]', text):
        offset += text_units(text[previous:match.start()])
        yield offset
        offset += 1
        previous = match.end()


def style_runs(runs, text):
    if not isinstance(runs, (tuple, list)):
        raise ValueError('Commentaires de marqueurs invalides.')
    result = []
    length = text_units(text)
    end = 0
    positions = box_positions(text)
    box = next(positions, length)
    for run in runs:
        if (not isinstance(run, (tuple, list)) or len(run) != 3
                or any(type(value) is not int for value in run)
                or not end <= run[0] < run[1] <= length or not 1 <= run[2] <= 15):
            raise ValueError('Commentaires de marqueurs invalides.')
        start, end, mask = run
        while box < start:
            box = next(positions, length)
        while box < end:
            if start < box:
                result.append((start, box, mask))
            start = box + 1
            box = next(positions, length)
        if start < end:
            result.append((start, end, mask))
    return tuple(result)


def frame_ranges(value, length):
    ranges = {}
    for part in value.split(','):
        match = re.fullmatch(r'\s*([0-9]{1,12})\s*(?:[-–]\s*([0-9]{1,12})\s*)?', part)
        if not match:
            raise ValueError('Plage d’images invalide.')
        start = int(match[1])
        end = int(match[2] or start)
        if not 0 <= start <= end < length:
            raise ValueError('Plage d’images invalide.')
        ranges[start] = max(ranges.get(start, 1), end - start + 1)
    return ranges
