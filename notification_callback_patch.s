.text
.p2align 2
.globl _shundo_notification_callback
_shundo_notification_callback:
    sub sp, sp, #0x60
    stp x29, x30, [sp, #0x50]
    stp x19, x20, [sp, #0x10]
    stp x21, x22, [sp, #0x20]
    stp x0, x1, [sp, #0x30]
    stp x2, x3, [sp, #0x40]

    adrp x0, 0
    add x0, x0, #0
    bl 0
    adrp x2, 0
    add x2, x2, #0
    bl 0
    bl 0
    mov x19, x0

    ldr x0, [sp, #0x40]
    adrp x8, 0
    ldr x1, [x8, #0x450]
    bl 0
    mov x1, x19
    bl 0
    mov x20, x0

    adrp x0, 0
    add x0, x0, #0
    bl 0
    adrp x2, 0
    add x2, x2, #0
    bl 0
    mov x1, x20
    bl 0

    ldp x0, x1, [sp, #0x30]
    ldp x2, x3, [sp, #0x40]
    bl 0
    ldp x21, x22, [sp, #0x20]
    ldp x19, x20, [sp, #0x10]
    ldp x29, x30, [sp, #0x50]
    add sp, sp, #0x60
    ret
