ENTRY(_start)
PHDRS { text PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); }
SECTIONS {
 . = 0x10000;
 .text : { *(.text*) *(.rodata*) } :text
 . = ALIGN(0x1000);
 .data : { *(.data*) *(.bss*) } :data
 /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) }
}
