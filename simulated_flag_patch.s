.text
.set objc_getClass_stub, 0x6d6710
.set class_getInstanceMethod_stub, 0x6d6284
.set method_setImplementation_stub, 0x6d6644

.org 0x130224
mov x20, x19
adrp x0, 0x6ef000
add x0, x0, #0x820
bl objc_getClass_stub
adrp x8, 0xc14000
ldr x1, [x8, #0xc0]
bl class_getInstanceMethod_stub
adrp x1, -0x2000
add x1, x1, #0x0
bl method_setImplementation_stub
mov x19, x20
nop
nop
nop
nop
