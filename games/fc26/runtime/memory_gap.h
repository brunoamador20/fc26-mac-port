#pragma once
#include <stdint.h>
#include <stddef.h>
#include "runtime.h"

/* Block of memory the runtime does not own around addr, between the known regions (memory_gap.c). */
void memory_gap_find(uint64_t addr, const MemoryRegion *ranges, size_t count, uint64_t *base_out, uint64_t *size_out);
