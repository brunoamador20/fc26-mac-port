#pragma once
#include <mach/mach.h>
#include <mach/mach_vm.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <errno.h>
#include <math.h>
/* Explicit read-only diagnostic. Kernel-checked copy also handles absent settings. */
static int fc26_live_copy(uint64_t address, void *out, size_t size) {
    mach_vm_size_t read = 0;
    kern_return_t kr = mach_vm_read_overwrite(mach_task_self(), address, size,
        (mach_vm_address_t)out, &read);
    if (kr != KERN_SUCCESS || read != size)
        fprintf(stderr, "[fc26-gameplay] read failed at %#llx: kernel=%d size=%llu/%zu\n",
                (unsigned long long)address, kr, (unsigned long long)read, size);
    return kr == KERN_SUCCESS && read == size;
}
/* Opt-in diagnostic only. Caller must establish the pre-match menu window;
 * kernel-checked memory access does not establish guest thread quiescence. */
static int fc26_gameplay_set(uint8_t *base, FILE *out, const char *field, const char *text) {
    uint64_t obj=0;
    if (!strcmp(field,"DeltaTicks") || !strcmp(field,"Gen")) goto refused;
    if (!base || !fc26_live_copy((uint64_t)base+0xc665768,&obj,8) || !obj) goto refused;
    for (unsigned i=0;i<78;i++) {
        uint64_t row[4]; char name[160]={0};
        if (!fc26_live_copy((uint64_t)base+0xb7c3558+i*32,row,sizeof row) ||
            !fc26_live_copy(row[0],name,sizeof name) || !memchr(name,0,sizeof name)) goto refused;
        if (strcmp(name,field)) continue;
        uint64_t type=row[3]-(uint64_t)base;
        uint32_t value=0, before=0, after=0; size_t width=4;
        char *end=NULL; errno=0;
        if (type==0xcb8c6d0) {
            if (strcmp(text,"0") && strcmp(text,"1")) goto refused;
            width=1; value=(uint32_t)(text[0]-'0');
        } else if (type==0xcb889a0) {
            if (!*text || strspn(text,"0123456789")!=strlen(text)) goto refused;
            unsigned long long n=strtoull(text,&end,10);
            if (errno || *end || n>UINT32_MAX) goto refused;
            value=(uint32_t)n;
        } else if (type==0xcb8c6b0) {
            float f=strtof(text,&end);
            if (end==text || *end || errno || !isfinite(f)) goto refused;
            memcpy(&value,&f,4);
        } else goto refused;
        /* Protect the forbidden fields even if metadata names are corrupt. */
        if (row[2]<0x28 || row[2]>0x82 || row[2]+width>0x83 ||
            (width==4 && row[2]%4)) goto refused;
        uint64_t current=0;
        if (!fc26_live_copy((uint64_t)base+0xc665768,&current,8) || current!=obj ||
            !fc26_live_copy(obj+row[2],&before,width)) goto refused;
        if (type==0xcb8c6b0) {
            float old; memcpy(&old,&before,4);
            fprintf(out,"[fc26-gameplay] set %s before=%g requested=%s (float)\n",field,old,text);
        } else fprintf(out,"[fc26-gameplay] set %s before=%u requested=%u (%s)\n",field,before,value,width==1?"bool":"uint32");
        kern_return_t kr=mach_vm_write(mach_task_self(),obj+row[2],(vm_offset_t)&value,(mach_msg_type_number_t)width);
        if (kr!=KERN_SUCCESS || !fc26_live_copy(obj+row[2],&after,width)) goto refused;
        fprintf(out,"[fc26-gameplay] set %s after_bits=%#x %s\n",field,after,after==value?"OK":"FAILED");
        return after==value;
    }
refused:
    fprintf(out,"[fc26-gameplay] REFUSED set %s\n",field);
    return 0;
}
static int fc26_gameplay_read(uint8_t *base, FILE *out) {
    uint64_t obj = 0, regulator = 0;
    if (!base || !fc26_live_copy((uint64_t)base + 0xc665768, &obj, 8) || !obj) {
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
    if (!fc26_live_copy((uint64_t)base + 0xc712880, &regulator, 8) || !regulator) {
        fprintf(out, "[fc26-gameplay] FAILED: ThreeLaneTimeRegulatorSettings unavailable (GameplayFeatures above read independently)\n");
        return 0;
    }
    float sim, render;
    if (!fc26_live_copy(regulator+0x20,&sim,4) || !fc26_live_copy(regulator+0x24,&render,4)) return 0;
    fprintf(out,"[fc26-gameplay] ThreeLaneTimeRegulatorSettings +0x20=%g +0x24=%g\n",sim,render);
    return 1;
}
