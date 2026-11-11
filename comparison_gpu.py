# SPDX-License-Identifier: GPL-3.0-only
LAYOUTS={'horizontal':1,'vertical':2,'wipe':3,'front':4}


class FramePacket(tuple):
    def __new__(cls,values,mode='single',swapped=False,wipe=.5):
        packet=super().__new__(cls,values)
        packet.opacity=.5; packet.gain=1.
        packet.layout=LAYOUTS.get(mode,0); packet.swapped=bool(swapped); packet.wipe=float(wipe)
        return packet
