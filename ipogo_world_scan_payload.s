.section __TEXT,__text,regular,pure_instructions
.p2align 2
.globl _shundo_world_mutation_entry

// The four scanner Array modify-resume thunks are redirected here. Their
// original job (ending Swift's exclusive access) remains first and
// authoritative. Only after the mutation has completed do we read counts.
_shundo_world_mutation_entry:
    sub sp, sp, #0x70
    stp x29, x30, [sp, #0x60]
    stp x19, x20, [sp, #0x20]
    stp x21, x22, [sp, #0x30]
    stp x23, x24, [sp, #0x40]
    stp x25, x26, [sp, #0x50]
    add x29, sp, #0x60
    // SHUNDO_WORLD_END_ACCESS_BL_MARKER
    .inst 0x97fffff7

    // SHUNDO_WORLD_WILD_GETTER_BL_MARKER
    .inst 0x97fffff6
    bl L_array_count_and_release
    mov x19, x0

    // SHUNDO_WORLD_NEARBY_GETTER_BL_MARKER
    .inst 0x97fffff5
    bl L_array_count_and_release
    mov x20, x0

    // SHUNDO_WORLD_GYM_GETTER_BL_MARKER
    .inst 0x97fffff4
    bl L_array_count_and_release
    mov x21, x0

    // SHUNDO_WORLD_STOP_GETTER_BL_MARKER
    .inst 0x97fffff3
    bl L_array_count_and_release
    mov x22, x0

    // Build the cave-local format as an NSString, then publish one structured
    // unified-log marker. No notifications or scanner state are modified.
    // SHUNDO_WORLD_CLASS_ADRP_MARKER
    .inst 0x90ffffe0
    // SHUNDO_WORLD_CLASS_ADD_MARKER
    .inst 0x91ffffe0
    // SHUNDO_WORLD_OBJC_GET_CLASS_BL_MARKER
    .inst 0x97fffffa
    // SHUNDO_WORLD_FORMAT_ADRP_MARKER
    .inst 0x90ffffc2
    // SHUNDO_WORLD_FORMAT_ADD_MARKER
    .inst 0x91ffffc2
    // SHUNDO_WORLD_UTF8_BL_MARKER
    .inst 0x97fffff9
    mov x1, x19
    mov x2, x20
    mov x3, x21
    mov x4, x22
    // SHUNDO_WORLD_NSLOG_BL_MARKER
    .inst 0x97fffff8

    ldp x25, x26, [sp, #0x50]
    ldp x23, x24, [sp, #0x40]
    ldp x21, x22, [sp, #0x30]
    ldp x19, x20, [sp, #0x20]
    ldp x29, x30, [sp, #0x60]
    add sp, sp, #0x70
    ret

// Existing static Array getters return an owned bridge object. Read only the
// native storage count, cap corrupt/unsupported representations to zero, and
// balance the getter's retain before returning the POD count.
L_array_count_and_release:
    stp x20, x19, [sp, #-0x20]!
    stp x29, x30, [sp, #0x10]
    add x29, sp, #0x10
    mov x19, x0
    mov x20, xzr
    cbz x19, L_count_return
    lsr x8, x19, #62
    cbnz x8, L_count_release
    and x8, x19, #0xfffffffffffffff8
    ldr x20, [x8, #0x10]
    cmp x20, #0x1000
    csel x20, x20, xzr, lo
L_count_release:
    mov x0, x19
    // SHUNDO_WORLD_BRIDGE_RELEASE_BL_MARKER
    .inst 0x97fffff2
L_count_return:
    mov x0, x20
    ldp x29, x30, [sp, #0x10]
    ldp x20, x19, [sp], #0x20
    ret

.p2align 2
L_world_class:
    .asciz "NSString"
L_world_format:
    .asciz "SHUNDO_WORLD_SCAN_V3 wild=%llu nearby=%llu gyms=%llu stops=%llu"
