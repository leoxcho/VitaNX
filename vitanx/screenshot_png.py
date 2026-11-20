"""Bounded PNG RGBA8 decoder for retained screenshot overlays (PNG filters0..4).

Independently implemented from the PNG chunk/filter specification. No image is
synthesized. Other PNG formats remain explicitly unsupported by this subset.
"""
import struct
import zlib

MAX_BYTES=4*1024*1024

def decode_rgba8(raw):
    if len(raw)>MAX_BYTES or raw[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('not a bounded PNG')
    offset=8;header=None;compressed=bytearray();ended=False;idat=False;idat_ended=False
    while offset<len(raw):
        if offset+12>len(raw):raise ValueError('truncated PNG chunk')
        length=struct.unpack_from('>I',raw,offset)[0];kind=raw[offset+4:offset+8]
        end=offset+12+length
        if end>len(raw):raise ValueError('truncated PNG payload')
        data=raw[offset+8:offset+8+length]
        crc=struct.unpack_from('>I',raw,offset+8+length)[0]
        if zlib.crc32(kind+data)&0xffffffff!=crc:raise ValueError('PNG CRC mismatch')
        if header is None and kind!=b'IHDR':raise ValueError('PNG header must be first')
        if kind==b'IHDR':
            if header is not None or length!=13:raise ValueError('invalid PNG header')
            width,height,depth,color,compression,filtering,interlace=struct.unpack('>IIBBBBB',data)
            if not 1<=width<=960 or not 1<=height<=544:raise ValueError('overlay exceeds compatibility dimensions')
            if (depth,color,compression,filtering,interlace)!=(8,6,0,0,0):raise ValueError('only noninterlaced PNG RGBA8 supported')
            header=(width,height)
        elif kind==b'IDAT':
            if idat_ended:raise ValueError('nonconsecutive PNG data')
            idat=True;compressed.extend(data)
        elif kind==b'IEND':
            if length or not idat or end!=len(raw):raise ValueError('invalid PNG end')
            ended=True;break
        else:
            if idat:idat_ended=True
            if not kind[0]&32 and kind!=b'PLTE':raise ValueError('unknown critical PNG chunk')
        offset=end
    if not ended:raise ValueError('PNG missing end')
    width,height=header;stride=width*4;expected=(stride+1)*height
    decoder=zlib.decompressobj()
    try:filtered=decoder.decompress(bytes(compressed),expected+1)
    except zlib.error as error:raise ValueError('invalid PNG compression') from error
    if len(filtered)!=expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:raise ValueError('PNG data size mismatch')
    pixels=bytearray(stride*height);previous=bytes(stride)
    for y in range(height):
        start=y*(stride+1);mode=filtered[start];line=bytearray(filtered[start+1:start+1+stride])
        if mode>4:raise ValueError('unsupported PNG filter')
        for x in range(stride):
            left=line[x-4] if x>=4 else 0;up=previous[x];upper_left=previous[x-4] if x>=4 else 0
            if mode==1:predictor=left
            elif mode==2:predictor=up
            elif mode==3:predictor=(left+up)//2
            elif mode==4:
                p=left+up-upper_left;a=abs(p-left);b=abs(p-up);c=abs(p-upper_left)
                predictor=left if a<=b and a<=c else up if b<=c else upper_left
            else:predictor=0
            line[x]=(line[x]+predictor)&255
        pixels[y*stride:(y+1)*stride]=line;previous=line
    return width,height,bytes(pixels)
