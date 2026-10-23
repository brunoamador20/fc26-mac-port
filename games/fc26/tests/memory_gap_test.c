#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <inttypes.h>
#include "../runtime/memory_gap.h"

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: %s <case>\n", argv[0]);
        return 1;
    }
    const char *tc = argv[1];

    if (!strcmp(tc, "ordered")) {
        MemoryRegion r[] = {
            {0x1000, 0x2000},
            {0x4000, 0x6000},
            {0x8000, 0x9000}
        };
        uint64_t base = 0, size = 0;
        memory_gap_find(0x3000, r, 3, &base, &size);
        if (base != 0x2000 || size != 0x2000) {
            fprintf(stderr, "FAIL ordered: expected base=0x2000 size=0x2000, got base=0x%" PRIx64 " size=0x%" PRIx64 "\n", base, size);
            return 1;
        }
        printf("PASS ordered: base=0x%" PRIx64 " size=0x%" PRIx64 "\n", base, size);
        return 0;
    }

    if (!strcmp(tc, "unordered")) {
        MemoryRegion r[] = {
            {0x8000, 0x9000},
            {0x1000, 0x2000},
            {0x4000, 0x6000}
        };
        uint64_t base = 0, size = 0;
        memory_gap_find(0x3000, r, 3, &base, &size);
        if (base != 0x2000 || size != 0x2000) {
            fprintf(stderr, "FAIL unordered: expected base=0x2000 size=0x2000, got base=0x%" PRIx64 " size=0x%" PRIx64 "\n", base, size);
            return 1;
        }
        printf("PASS unordered: base=0x%" PRIx64 " size=0x%" PRIx64 "\n", base, size);
        return 0;
    }

    if (!strcmp(tc, "between")) {
        MemoryRegion r[] = {
            {0x100000, 0x200000},
            {0x500000, 0x700000}
        };
        uint64_t base = 0, size = 0;
        memory_gap_find(0x300000, r, 2, &base, &size);
        if (base != 0x200000 || size != 0x300000) {
            fprintf(stderr, "FAIL between: expected base=0x200000 size=0x300000, got base=0x%" PRIx64 " size=0x%" PRIx64 "\n", base, size);
            return 1;
        }
        printf("PASS between: base=0x%" PRIx64 " size=0x%" PRIx64 "\n", base, size);
        return 0;
    }

    if (!strcmp(tc, "above_all")) {
        MemoryRegion r[] = {
            {0x1000, 0x2000},
            {0x4000, 0x8000}
        };
        uint64_t base = 0, size = 0;
        memory_gap_find(0x9000, r, 2, &base, &size);
        uint64_t expected_size = (uint64_t)0 - 0x8000;
        if (base != 0x8000 || size != expected_size) {
            fprintf(stderr, "FAIL above_all: expected base=0x8000 size=0x%" PRIx64 ", got base=0x%" PRIx64 " size=0x%" PRIx64 "\n", expected_size, base, size);
            return 1;
        }
        printf("PASS above_all: base=0x%" PRIx64 " size=0x%" PRIx64 "\n", base, size);
        return 0;
    }

    if (!strcmp(tc, "below_all")) {
        MemoryRegion r[] = {
            {0x4000, 0x6000},
            {0x8000, 0x9000}
        };
        uint64_t base = 0, size = 0;
        memory_gap_find(0x2000, r, 2, &base, &size);
        if (base != 0x0 || size != 0x4000) {
            fprintf(stderr, "FAIL below_all: expected base=0x0 size=0x4000, got base=0x%" PRIx64 " size=0x%" PRIx64 "\n", base, size);
            return 1;
        }
        printf("PASS below_all: base=0x%" PRIx64 " size=0x%" PRIx64 "\n", base, size);
        return 0;
    }

    if (!strcmp(tc, "at_end")) {
        MemoryRegion r[] = {
            {0x1000, 0x2000},
            {0x4000, 0x5000}
        };
        uint64_t base = 0, size = 0;
        memory_gap_find(0x2000, r, 2, &base, &size);
        if (base != 0x2000 || size != 0x2000) {
            fprintf(stderr, "FAIL at_end: expected base=0x2000 size=0x2000, got base=0x%" PRIx64 " size=0x%" PRIx64 "\n", base, size);
            return 1;
        }
        printf("PASS at_end: base=0x%" PRIx64 " size=0x%" PRIx64 "\n", base, size);
        return 0;
    }

    fprintf(stderr, "unknown test case: %s\n", tc);
    return 1;
}
