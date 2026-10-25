#include "../runtime/gameplay_apply.h"
#include <assert.h>
#include <mach/mach_vm.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static uint8_t *synthetic_memory(void) {
    mach_vm_address_t address = 0;
    const mach_vm_size_t size = 0x10000000;
    assert(size > 0xc665768 + sizeof(uint64_t));
    assert(size > 0xb7c3558 + 78 * 32);
    assert(size > 0xc665768 + 0x1000);
    assert(mach_vm_allocate(mach_task_self(), &address, size, VM_FLAGS_ANYWHERE) == KERN_SUCCESS);
    memset((void *)address, 0, size);
    return (uint8_t *)address;
}

static void synthetic_table(uint8_t *base) {
    uint64_t object = (uint64_t)base + 0x200;
    const char *names[3] = {
        "EnableHighPrequencyPerceptionUpdate", "EnableExtraPassEvaluations",
        "EnablePPCriticalReducedEvaluation"
    };
    const uint8_t offsets[3] = {0x81, 0x5f, 0x51};
    memcpy(base + 0xc665768, &object, sizeof object);
    const uint64_t empty_name = (uint64_t)base + 0x1000 + 3 * 160;
    for (unsigned i = 0; i < 78; i++) {
        uint64_t row[4] = {empty_name, 0, 0x28, (uint64_t)base + 0xcb8c6d0};
        if (i < 3) {
            row[0] = (uint64_t)base + 0x1000 + i * 160;
            row[2] = offsets[i];
            memcpy(base + 0x1000 + i * 160, names[i], strlen(names[i]) + 1);
        } else {
            memset(base + 0x1000 + i * 160, 0, 160);
        }
        memcpy(base + 0xb7c3558 + i * 32, row, sizeof row);
    }
}

int main(void) {
    uint8_t *base = synthetic_memory();
    synthetic_table(base);
    FILE *out = tmpfile();
    assert(out);
    Fc26GameplayApply config = {.base = base, .out = out,
                                .entries = "EnableHighPrequencyPerceptionUpdate=1,"
                                           "EnableExtraPassEvaluations=1,"
                                           "EnablePPCriticalReducedEvaluation=0",
                                .interval_ms = 1};
    int ready = 0;
    pthread_t thread;
    atomic_init(&config.stop, false);
    assert(pthread_create(&thread, NULL, fc26_gameplay_apply_thread, &config) == 0);
    for (unsigned i = 0; i < 100 && !ready; i++) {
        usleep(1000);
        ready = base[0x281] == 1 && base[0x25f] == 1 && base[0x251] == 0;
    }
    assert(ready);
    uint64_t applied_object = 0;
    memcpy(&applied_object, base + 0xc665768, sizeof applied_object);
    assert(applied_object);
    base[0x281] = 0; base[0x25f] = 0; base[0x251] = 1;
    for (unsigned i = 0; i < 100; i++) {
        usleep(1000);
        if (base[0x281] == 1 && base[0x25f] == 1 && base[0x251] == 0) { ready = 2; break; }
    }
    assert(ready == 2);
    atomic_store(&config.stop, true);
    pthread_join(thread, NULL);
    memset(config.seen, 0, sizeof config.seen);

    config.entries = ".bogus=1";
    bool changed = false;
    assert(fc26_gameplay_apply_once(&config, &changed) < 0);
    assert(!changed);
    assert(!fc26_gameplay_allowed("DeltaTicks"));
    assert(!fc26_gameplay_allowed("Gen"));
    assert(!fc26_gameplay_allowed("CpuAiObjectivesUpdateMode"));
    assert(!fc26_gameplay_allowed("EnableNextGenLocomotion"));
    assert(fc26_gameplay_allowed("EnablePPAlternateFrameOptimization"));
    assert(!fc26_gameplay_allowed("EnableBogus"));

    config.entries = "EnableHighPrequencyPerceptionUpdate=1,"
                     "EnableExtraPassEvaluations=1,"
                     "EnablePPCriticalReducedEvaluation=0";
    memset(config.seen, 0, sizeof config.seen);
    assert(fc26_gameplay_apply_once(&config, &changed) == 1 && !changed);
    assert(base[0x281] == 1 && base[0x25f] == 1 && base[0x251] == 0);
    assert(fc26_gameplay_apply_once(&config, &changed) == 1 && !changed);
    base[0x281] = 0; base[0x25f] = 0; base[0x251] = 1;
    assert(fc26_gameplay_apply_once(&config, &changed) == 1 && changed);
    assert(base[0x281] == 1 && base[0x25f] == 1 && base[0x251] == 0);

    uint64_t original_object;
    memcpy(&original_object, base + 0xc665768, sizeof original_object);
    uint64_t empty = 0;
    memcpy(base + 0xc665768, &empty, sizeof empty);
    assert(fc26_gameplay_apply_once(&config, &changed) == 0 && !changed);
    memcpy(base + 0xc665768, &original_object, sizeof original_object);
    base[0x281] = 0;
    memset(config.seen, 0, sizeof config.seen);
    assert(fc26_gameplay_apply_once(&config, &changed) == 1 && changed);
    assert(base[0x281] == 1);

    rewind(out);
    char line[256];
    unsigned refused = 0, applied = 0, reapplied = 0;
    while (fgets(line, sizeof line, out)) {
        if (strstr(line, "REFUSED set .bogus") || strstr(line, "REFUSED malformed entry in FC26_GAMEPLAY_SET")) refused++;
        if (strstr(line, "[fc26-gameplay] applied ")) applied++;
        if (strstr(line, "[fc26-gameplay] reapplied ")) reapplied++;
    }
    assert(refused == 1);
    assert(applied == 7);     /* 3 by the thread, 3 after seen[] is cleared, 1 for the last single field */
    assert(reapplied == 2);   /* the thread restoring perception and passes; the reduced-evaluation field already held 0, so its first write counts as applied */
    fclose(out);
    mach_vm_deallocate(mach_task_self(), (mach_vm_address_t)base, 0xc700000);
    return 0;
}

uint8_t *runtime_module_base(const char *name) { (void)name; return NULL; }
void fc26_gameplay_apply_start(void);
void fc26_unused_functions(void) { fc26_gameplay_apply_start(); }
