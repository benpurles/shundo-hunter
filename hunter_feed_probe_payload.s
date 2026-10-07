.section __TEXT,__text,regular,pure_instructions
.p2align 2
.globl _hunter_feed_merge_entry
.globl _hunter_lab_initializer

// Read-only probe at iPogo's decoded feed merger. Both the initial HTTP
// snapshot and subsequent WebSocket deltas pass this boundary.
//
// Each original call site is `bl _feedMerger`. The builder redirects that call
// to this wrapper. After logging POD values only, the wrapper restores x0/x1
// and tail-branches to the original merger. The merger therefore returns
// directly to the untouched instruction following the hook.
_hunter_feed_merge_entry:
    sub sp, sp, #0xe0
    stp x29, x30, [sp, #0xd0]
    add x29, sp, #0xd0
    stp x19, x20, [sp, #0x80]
    stp x21, x22, [sp, #0x90]
    stp x23, x24, [sp, #0xa0]
    stp x25, x26, [sp, #0xb0]
    stp x27, x28, [sp, #0xc0]

    mov x19, x0
    mov x27, x1

    // Emit an unconditional boundary marker before inspecting storage or
    // resilient metadata. This distinguishes "the snapshot never completed"
    // from a decoder guard rejecting the returned array.
    // HUNTER_ENTRY_FORMAT_ADR_MARKER (patched to ADR x1, entry format)
    .inst 0x10ffffc1
    .inst 0x90ffffa8
    .inst 0xf9400108
    ldr x0, [x8]
    // HUNTER_ENTRY_FPRINTF_BL_MARKER
    .inst 0x97fffffa
    mov x0, xzr
    // HUNTER_ENTRY_FFLUSH_BL_MARKER
    .inst 0x97fffff9

    cbz x19, L_render_done
    ldr x20, [x19, #0x10]
    cbz x20, L_render_done
    cmp x20, #0x800
    b.hi L_render_done

    // Realize the feed record metadata before the first snapshot is inspected.
    // Calling Swift's own metadata accessor removes the launch-order race that
    // left its lazy cache empty at this earlier merger boundary.
    mov x0, xzr
    // HUNTER_METADATA_ACCESSOR_BL_MARKER
    .inst 0x97fffffb
    mov x21, x0
    cbz x21, L_render_done
    ldur x22, [x21, #-8]
    cbz x22, L_render_done
    ldr x23, [x22, #0x48]
    cbz x23, L_render_done
    cmp x23, #0x1000
    b.hs L_render_done
    ldrb w10, [x22, #0x50]
    add x11, x10, #0x20
    bic x11, x11, x10
    add x22, x19, x11
    mov x24, xzr

L_render_loop:
    madd x25, x24, x23, x22

    // Batch identity and fixed record fields.
    stp x19, x24, [sp]
    str x20, [sp, #0x10]
    ldr x8, [x25, #0x10]
    ldr x9, [x25, #0x20]
    ldr x10, [x25, #0x28]
    str x8, [sp, #0x18]
    stp x9, x10, [sp, #0x20]

    // Optional<Int> fields are an eight-byte payload followed by a tag byte.
    // The field offsets themselves are resiliently read from realized metadata.
    ldrsw x8, [x21, #0x28]
    add x8, x25, x8
    ldr x9, [x8]
    ldrb w10, [x8, #0x8]
    stp x9, x10, [sp, #0x30]
    ldrsw x8, [x21, #0x2c]
    add x8, x25, x8
    ldr x9, [x8]
    ldrb w10, [x8, #0x8]
    stp x9, x10, [sp, #0x40]
    ldrsw x8, [x21, #0x30]
    add x8, x25, x8
    ldr x9, [x8]
    ldrb w10, [x8, #0x8]
    stp x9, x10, [sp, #0x50]

    // Foundation.Date is logged as raw bits and decoded on the Mac. On this
    // ABI it is a Double measured from Apple's 2001 reference epoch.
    ldrsw x8, [x21, #0x24]
    ldr x9, [x25, x8]
    str x9, [sp, #0x60]

    // The feed's location array is [longitude, latitude]. Missing/short arrays
    // remain explicit zero bits instead of dereferencing invalid storage.
    stp xzr, xzr, [sp, #0x68]
    ldr x26, [x25, #0x18]
    cbz x26, L_render_emit
    ldr x8, [x26, #0x10]
    cmp x8, #2
    b.lo L_render_emit
    ldp x9, x10, [x26, #0x20]
    stp x9, x10, [sp, #0x68]

L_render_emit:
    // Preserve snapshot (1) versus delta (0) on every emitted row.
    str x27, [sp, #0x78]
    // HUNTER_RENDER_FORMAT_ADR_MARKER (patched to ADR x1, format)
    .inst 0x10ffffe0
    // Darwin stderr FILE* via the framework's existing lazy-symbol pointer.
    .inst 0x90ffffc8
    .inst 0xf9400508
    ldr x0, [x8]
    // Darwin arm64 variadic values already occupy consecutive stack slots.
    // HUNTER_RENDER_FPRINTF_BL_MARKER
    .inst 0x97fffffe

    add x24, x24, #1
    cmp x24, x20
    b.lo L_render_loop

    // Flush once after the bounded batch rather than once per row.
    mov x0, xzr
    // HUNTER_RENDER_FFLUSH_BL_MARKER
    .inst 0x97fffffc

L_render_done:
    mov x0, x19
    mov x1, x27
    ldp x27, x28, [sp, #0xc0]
    ldp x25, x26, [sp, #0xb0]
    ldp x23, x24, [sp, #0xa0]
    ldp x21, x22, [sp, #0x90]
    ldp x19, x20, [sp, #0x80]
    ldp x29, x30, [sp, #0xd0]
    add sp, sp, #0xe0
    // HUNTER_MERGER_TAIL_B_MARKER
    .inst 0x17fffffd

.p2align 2
// Replacement for one existing module initializer. It first runs the original
// initializer unchanged, then schedules the authenticated feed manager on the
// main queue after the app has finished restoring its account state.
_hunter_lab_initializer:
    // HUNTER_INITIALIZER_ENTRY_MARKER
    .inst 0xd503245f
    stp x20, x19, [sp, #-0x20]!
    stp x29, x30, [sp, #0x10]
    add x29, sp, #0x10
    // HUNTER_ORIGINAL_INITIALIZER_BL_MARKER
    .inst 0x97fffff8

    sub sp, sp, #0x20
    mov x0, xzr
    mov x1, #0x7800
    movk x1, #0xcb41, lsl #16
    movk x1, #0x2, lsl #32
    // HUNTER_DISPATCH_TIME_BL_MARKER
    .inst 0x97fffff7
    mov x19, x0

    // Stack block: isa, flags/reserved, invoke, descriptor. It has no captures.
    // HUNTER_STACK_BLOCK_ADRP_MARKER
    .inst 0x90ffff88
    // HUNTER_STACK_BLOCK_LDR_MARKER
    .inst 0xf9400188
    str x8, [sp]
    str xzr, [sp, #0x8]
    adr x8, L_auto_feed_invoke
    adr x9, L_auto_feed_descriptor
    stp x8, x9, [sp, #0x10]

    mov x0, x19
    // HUNTER_MAIN_QUEUE_ADRP_MARKER
    .inst 0x90ffff68
    // HUNTER_MAIN_QUEUE_LDR_MARKER
    .inst 0xf94001a1
    mov x2, sp
    // HUNTER_DISPATCH_AFTER_BL_MARKER
    .inst 0x97fffff6
    add sp, sp, #0x20
    ldp x29, x30, [sp, #0x10]
    ldp x20, x19, [sp], #0x20
    ret

.p2align 2
L_auto_feed_invoke:
    stp x20, x19, [sp, #-0x20]!
    stp x29, x30, [sp, #0x10]
    add x29, sp, #0x10
    // HUNTER_MANAGER_GETTER_BL_MARKER
    .inst 0x97fffff5
    mov x20, x0
    cbz x20, L_auto_feed_return
    // HUNTER_MANAGER_START_BL_MARKER
    .inst 0x97fffff4
    mov x0, x20
    // HUNTER_SWIFT_RELEASE_BL_MARKER
    .inst 0x97fffff3
L_auto_feed_return:
    ldp x29, x30, [sp, #0x10]
    ldp x20, x19, [sp], #0x20
    ret

.p2align 3
L_auto_feed_descriptor:
    .quad 0
    .quad 32

.p2align 2
L_render_format:
    .asciz "HUNTER_FEED_ITEM_V12 storage=%016llx index=%llu count=%llu pokemon=%lld form=%lld weather=%lld cp=%lld cpnil=%u iv=%lld ivnil=%u level=%lld levelnil=%u expirybits=%016llx lonbits=%016llx latbits=%016llx replace=%llu\n"
L_entry_format:
    .asciz "HUNTER_FEED_ENTRY_V12\n"
