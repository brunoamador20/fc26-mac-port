#pragma once
#include <mach/mach.h>
#include <mach/mach_vm.h>
#include <stdio.h>
#include <string.h>
/* Explicit read-only diagnostic. Kernel-checked copy also handles absent settings. */
static int fc26_live_copy(uint64_t address, void *out, size_t size) {
    mach_vm_size_t read = 0;
    return mach_vm_read_overwrite(mach_task_self(), address, size,
        (mach_vm_address_t)out, &read) == KERN_SUCCESS && read == size;
}
static int fc26_gameplay_read(uint8_t *base, FILE *out) {
    uint64_t obj = 0, regulator = 0;
    if (!base || !fc26_live_copy((uint64_t)base + 0xc665768, &obj, 8) || !obj ||
        !fc26_live_copy((uint64_t)base + 0xc712880, &regulator, 8) || !regulator) {
        fprintf(out, "[fc26-gameplay] FAILED: settings not available\n"); return 0;
    }
    fprintf(out, "[fc26-gameplay] read-only snapshot\n");
    for (unsigned i=0; i<78; i++) {
        uint64_t row[4]; char name[160] = {0}; uint32_t value = 0;
        if (!fc26_live_copy((uint64_t)base + 0xb7c3558 + i*32, row, sizeof row) ||
            row[2] > 0x1000 || !fc26_live_copy(row[0], name, sizeof name-1)) {
            fprintf(out,"[fc26-gameplay] FAILED: field %u\n",i); return 0;
        }
        uint64_t type = row[3] - (uint64_t)base;
        size_t width = type == 0xcb8c6d0 ? 1 : 4;
        if (!fc26_live_copy(obj + row[2], &value, width)) return 0;
        if (type == 0xcb8c6b0) {
            float f; memcpy(&f, &value, 4);
            fprintf(out,"[fc26-gameplay] %s +%#llx = %g (float)\n",name,(unsigned long long)row[2],f);
        } else fprintf(out,"[fc26-gameplay] %s +%#llx = %u (%s, type main+%#llx)\n",name,(unsigned long long)row[2],value,width==1?"bool":"integer",(unsigned long long)type);
    }
    float sim, render;
    if (!fc26_live_copy(regulator+0x20,&sim,4) || !fc26_live_copy(regulator+0x24,&render,4)) return 0;
    fprintf(out,"[fc26-gameplay] ThreeLaneTimeRegulatorSettings +0x20=%g +0x24=%g\n",sim,render);
    return 1;
}
