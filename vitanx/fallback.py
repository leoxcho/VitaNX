"""Bounded translation cache used by the live native dispatcher.

Live mode grows the original static graph with observed executable targets.
NativeSession owns compilation/loading and resumes shared state without replay.
"""
import hashlib
from pathlib import Path
from vitaxnative.recompiler import translate_elf

class TranslationCache:
    def __init__(self, source, max_blocks=32, *, imports=None, live=False, decode_traps=False, translation_limit=4096,region_entry=False,partial_regions=False):
        self.source=Path(source)
        if type(max_blocks) is not int or not 1<=max_blocks<=4096:
            raise ValueError('invalid block budget')
        self.digest=hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.max_blocks=max_blocks
        self.blocks={}
        self.imports=imports
        self.live=live
        self.decode_traps=decode_traps
        self.translation_limit=translation_limit
        self.region_entry=region_entry
        self.partial_regions=partial_regions

    def request(self, tagged_pc):
        if type(tagged_pc) is not int or not 0<=tagged_pc<=0xffffffff:
            raise ValueError('invalid guest PC')
        if hashlib.sha256(self.source.read_bytes()).hexdigest()!=self.digest:
            raise ValueError('input changed; invalidate translation cache')
        if tagged_pc not in self.blocks:
            if len(self.blocks)>=self.max_blocks:
                raise RuntimeError('translation cache budget exhausted')
            self.blocks[tagged_pc]=translate_elf(self.source,imports=self.imports,entry=tagged_pc if self.region_entry else None,indirect_targets=() if self.region_entry else ([*self.blocks,tagged_pc] if self.live else [tagged_pc]),max_instructions=self.translation_limit,runtime_fallback=self.live,defer_decode_errors=self.decode_traps,partial_regions=self.partial_regions)
        return self.blocks[tagged_pc]
