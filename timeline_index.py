# SPDX-License-Identifier: GPL-3.0-only
from bisect import bisect_left,bisect_right
from itertools import accumulate


class SegmentIndex:
    def __init__(self):
        self.segments=(); self.ends=()

    def visible(self,segments,start,end):
        if segments is not self.segments:
            self.segments=segments; self.ends=tuple(accumulate(s.length for s in segments))
        index=bisect_left(self.ends,start)
        at=self.ends[index-1] if index else 0
        while index<len(segments) and at<=end:
            yield index,at,segments[index]
            at=self.ends[index]; index+=1


def visible_keys(keys,start,end):
    first=bisect_left(keys,start,key=lambda k:k.end)
    last=bisect_right(keys,end,key=lambda k:k.start)
    for index in range(first,last): yield keys[index]
