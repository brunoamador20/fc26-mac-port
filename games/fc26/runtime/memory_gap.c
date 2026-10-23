#include "memory_gap.h"

/* svcQueryMemory for memory the runtime does not own (host code, dylibs, malloc, nothing mapped): the largest block
   [base, base+size) around addr that touches no known region. Below every region, base = 0; above every region, the
   block runs to the end of the 64-bit space (size = 0 - base), as Horizon reports Inaccessible past the process space. */
void memory_gap_find(uint64_t addr, const MemoryRegion *ranges, size_t count, uint64_t *base_out, uint64_t *size_out) {
    uint64_t base = 0;
    uint64_t limit = 0;
    int has_limit = 0;

    for (size_t i = 0; i < count; i++) {
        uint64_t s = ranges[i].start;
        uint64_t e = ranges[i].end;
        if (e <= s) continue; /* empty or inverted */

        /* ends at or below addr */
        if (e <= addr && e > base) {
            base = e;
        }

        /* starts above addr */
        if (s > addr) {
            if (!has_limit || s < limit) {
                limit = s;
                has_limit = 1;
            }
        }
    }

    *base_out = base;
    if (has_limit) {
        *size_out = limit - base;
    } else {
        *size_out = (uint64_t)0 - base;
    }
}
