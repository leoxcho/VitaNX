"""Bounded read-only PSARC/zlib access for inspecting packaged game resources."""
from pathlib import Path
import struct
import zlib

MAX_TABLE=16*1024*1024
MAX_MEMBER=16*1024*1024


class Psarc:
    def __init__(self,path):
        self.path=Path(path);self.size=self.path.stat().st_size
        with self.path.open('rb') as stream:
            header=stream.read(32)
            if len(header)!=32:raise ValueError('truncated PSARC header')
            magic,version,codec,toc,stride,count,block,flags=struct.unpack('>4sI4sIIIII',header)
            if magic!=b'PSAR' or version!=0x10004 or codec!=b'zlib' or stride!=30:
                raise ValueError('unsupported PSARC format/version/compression')
            if block<256 or block>1024*1024 or block&(block-1) or flags&~3:
                raise ValueError('unsupported PSARC block size/flags')
            if not count or count>65536 or not 32+count*stride<=toc<=min(self.size,MAX_TABLE):
                raise ValueError('invalid PSARC table bounds')
            table=stream.read(toc-32)
        self.block=block;self.entries=[]
        width=((block-1).bit_length()+7)//8
        sizes=table[count*stride:]
        if len(sizes)%width:raise ValueError('truncated PSARC block table')
        self.blocks=[int.from_bytes(sizes[i:i+width],'big') or block for i in range(0,len(sizes),width)]
        for i in range(count):
            entry=table[i*stride:(i+1)*stride]
            index=int.from_bytes(entry[16:20],'big');length=int.from_bytes(entry[20:25],'big')
            offset=int.from_bytes(entry[25:30],'big');n=(length+block-1)//block
            if index+n>len(self.blocks) or offset<toc or offset>self.size:
                raise ValueError('PSARC entry outside archive/table')
            compressed=sum(self.blocks[index:index+n])
            if compressed>self.size-offset:raise ValueError('PSARC entry data truncated')
            self.entries.append({'index':i,'block_index':index,'size':length,'offset':offset,'stored_size':compressed})
        data_ranges=sorted((e['offset'],e['offset']+e['stored_size']) for e in self.entries if e['stored_size'])
        if any(a[1]>b[0] for a,b in zip(data_ranges,data_ranges[1:])):
            raise ValueError('overlapping PSARC entry data')
        manifest=self.read_index(0).decode('utf-8').splitlines()
        if len(manifest)!=count-1:raise ValueError('PSARC filename count mismatch')
        self.names={}
        for i,name in enumerate(manifest,1):
            normalized=name.lstrip('/')
            if not normalized or '\\' in normalized or any(p in ('','.','..') for p in normalized.split('/')) or normalized in self.names:
                raise ValueError('unsafe or duplicate PSARC member name')
            self.names[normalized]=i

    def read_index(self,index):
        entry=self.entries[index]
        if entry['size']>MAX_MEMBER:raise ValueError('PSARC member exceeds inspection limit')
        result=bytearray();remaining=entry['size'];block=entry['block_index']
        with self.path.open('rb') as stream:
            stream.seek(entry['offset'])
            while remaining:
                expected=min(self.block,remaining);stored=self.blocks[block];block+=1
                if stored>self.block:raise ValueError('invalid PSARC compressed block length')
                data=stream.read(stored)
                if len(data)!=stored:raise ValueError('truncated PSARC data block')
                if stored!=expected:
                    decoder=zlib.decompressobj()
                    try:data=decoder.decompress(data,expected+1)
                    except zlib.error as error:raise ValueError('invalid PSARC zlib block') from error
                    if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                        raise ValueError('invalid/trailing PSARC zlib data')
                if len(data)!=expected:raise ValueError('PSARC block output length mismatch')
                result.extend(data);remaining-=expected
        return bytes(result)

    def read(self,name):
        if name not in self.names:raise ValueError('PSARC member not found')
        return self.read_index(self.names[name])

    def inventory(self):
        return {'path':str(self.path),'format':'PSARC/zlib','members':[
            {'name':name,**self.entries[index]} for name,index in self.names.items()]}
