/* Module-relative offsets as text (games/fc26/docs/ILHAS_NUVEM.md). The pre-island is mapped just before a module's
   base, so a pc there has a NEGATIVE offset: it is always written as signed hex, "main-0x1234", never as the wrapped
   0xffff... of an unsigned pc - base; offsets at or after base keep the usual "main+0x1234" (what scripts/symbolize.py
   reads). No libc call, so crash() can use it from the signal handler. Portable: tests/test_module_offset.py compiles it. */
#ifndef FC26_MODULE_OFFSET_H
#define FC26_MODULE_OFFSET_H
#include <stddef.h>
#include <stdint.h>

/* off is pc - base as an unsigned (two's-complement) subtraction, negative in the pre-island. Writes "+0x<hex>" or
   "-0x<hex>" (shortest hex, at least one digit) and a NUL into out, which needs MODULE_OFFSET_HEX bytes; returns the
   length without the NUL. */
#define MODULE_OFFSET_HEX 20
static inline size_t module_offset_hex(char *out, uint64_t off) {
    int neg = (int64_t)off < 0; uint64_t v = neg ? (uint64_t)0 - off : off; size_t n = 0; int i = 15;
    out[n++] = neg ? '-' : '+'; out[n++] = '0'; out[n++] = 'x';
    while (i > 0 && !((v >> (i * 4)) & 15)) i--;
    for (; i >= 0; i--) out[n++] = "0123456789abcdef"[(v >> (i * 4)) & 15];
    out[n] = 0;
    return n;
}
#endif
