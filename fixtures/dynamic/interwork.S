.syntax unified
.arch armv7-a
.fpu neon
.section .text
.arm
.global _start
_start:
    push {r4-r8,lr}
    movw r4, #:lower16:counter
    movt r4, #:upper16:counter
    ldr r5, [r4, #4]
    mov r0, #7
    vmov s0, r0
    cmp r0, #7
    ldrex r6, [r4]
    blx r5
    cmp r7, #0
    bne failure
    ldr r0, [r4]
    cmp r0, #42
    bne failure
    vmov r1, s0
    cmp r1, #7
    bne failure
    mov r0, #1
    movw r1, #:lower16:message
    movt r1, #:upper16:message
    mov r2, #24
    movw r5, #0x2000
    blx r5
    cmp r0, #24
    bne failure
    mov r0, #42
    pop {r4-r8,pc}
failure:
    mov r0, #99
    pop {r4-r8,pc}
.thumb
.thumb_func
worker:
    it eq
    addeq.w r6, r6, #1
    strex r7, r6, [r4]
    vmov r8, s0
    add.w r8, r8, #5
    bx lr
message: .ascii "vitanx live translation\n"
.section .data
.align 2
counter: .word 41
.word worker
