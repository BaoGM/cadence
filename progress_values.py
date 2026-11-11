# SPDX-License-Identifier: GPL-3.0-only
import logging
import math


def bounded_progress(value,previous=0.,context='task'):
    try: number=float(value)
    except (TypeError,ValueError,OverflowError): number=float('nan')
    if not math.isfinite(number):
        logging.warning('Progress unavailable: context=%s value=%r type=%s previous=%r',context,value,type(value).__name__,previous)
        return previous
    result=max(previous,min(1.,max(0.,number)))
    if not 0<=number<=1:
        logging.warning('Progress outside range: context=%s value=%r type=%s normalized=%r',context,value,type(value).__name__,result)
    return result


class FFmpegProgress:
    def __init__(self,duration):
        try: self.duration=float(duration)
        except (TypeError,ValueError,OverflowError): self.duration=0.
        if not math.isfinite(self.duration) or self.duration<=0: self.duration=0.
        self.value=0.; self.reported_unavailable=False
    def update(self,raw):
        try: timestamp=int(raw)
        except (TypeError,ValueError): timestamp=None
        if timestamp is None or timestamp<0 or not self.duration:
            if not self.reported_unavailable:
                logging.info('FFmpeg progress unavailable: out_time_us=%r type=%s duration=%r type=%s; retaining=%r',raw,type(raw).__name__,self.duration,type(self.duration).__name__,self.value)
                self.reported_unavailable=True
            return self.value
        end=self.duration*1_000_000
        fraction=.99 if timestamp>=end else timestamp/end
        self.value=max(self.value,min(.99,fraction))
        logging.info('FFmpeg progress: out_time_us=%r type=%s duration=%r fraction=%r',timestamp,type(timestamp).__name__,self.duration,self.value)
        return self.value
