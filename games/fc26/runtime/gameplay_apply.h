#pragma once
#include "gameplay_read.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <time.h>

uint8_t *runtime_module_base(const char *name);

typedef struct Fc26GameplayApply {
    uint8_t *base;
    FILE *out;
    const char *entries;
    uint64_t interval_ms;
    atomic_bool stop;
    bool seen[4];
} Fc26GameplayApply;

static const char *const fc26_gameplay_allowed_fields[4] = {
    "EnableHighPrequencyPerceptionUpdate", "EnableExtraPassEvaluations",
    "EnablePPCriticalReducedEvaluation", "EnablePPAlternateFrameOptimization"
};

static bool fc26_gameplay_allowed(const char *name) {
    for (unsigned index = 0; index < 4; index++)
        if (!strcmp(name, fc26_gameplay_allowed_fields[index])) return true;
    return false;
}

static int fc26_gameplay_table_ready(uint8_t *base) {
    uint64_t object = 0;
    if (!base || !fc26_live_copy((uint64_t)base + 0xc665768, &object, 8) || !object) return 0;
    for (unsigned i = 0; i < 78; i++) {
        uint64_t row[4]; char name[160] = {0};
        if (!fc26_live_copy((uint64_t)base + 0xb7c3558 + i * 32, row, sizeof row) ||
            !fc26_live_copy(row[0], name, sizeof name) || !memchr(name, 0, sizeof name)) return 0;
    }
    return 1;
}

static int fc26_gameplay_field_address(uint8_t *base, const char *field, uint64_t *address) {
    uint64_t object = 0;
    if (!base || !fc26_live_copy((uint64_t)base + 0xc665768, &object, 8) || !object) return 0;
    for (unsigned i = 0; i < 78; i++) {
        uint64_t row[4]; char name[160] = {0};
        if (!fc26_live_copy((uint64_t)base + 0xb7c3558 + i * 32, row, sizeof row) ||
            !fc26_live_copy(row[0], name, sizeof name) || !memchr(name, 0, sizeof name)) return 0;
        if (strcmp(name, field)) continue;
        if (row[3] - (uint64_t)base != 0xcb8c6d0 || row[2] < 0x28 || row[2] > 0x82) return -1;
        *address = object + row[2];
        return 1;
    }
    return -1;
}

static int fc26_gameplay_object_current(uint8_t *base, uint64_t *object) {
    if (!base || !fc26_live_copy((uint64_t)base + 0xc665768, object, 8) || !*object) return 0;
    return 1;
}

static int fc26_gameplay_field_current(uint8_t *base, const char *field, uint8_t *current) {
    uint64_t address = 0;
    uint64_t object = 0;
    if (!fc26_gameplay_object_current(base, &object)) return 0;
    int state = fc26_gameplay_field_address(base, field, &address);
    if (state > 0) {
        if (!fc26_live_copy(address, current, 1)) return 0;
        return 1;
    }
    return state;
}

static int fc26_gameplay_field_write(uint8_t *base, FILE *out, const char *field, uint8_t value) {
    uint64_t address = 0;
    int state = fc26_gameplay_field_address(base, field, &address);
    if (state <= 0) return state;
    uint8_t before = 0;
    if (!fc26_live_copy(address, &before, 1)) return 0;
        fprintf(out, "[fc26-gameplay] set %s before=%u requested=%u (bool)\n", field, before, value);
    if (mach_vm_write(mach_task_self(), address, (vm_offset_t)&value, 1) != KERN_SUCCESS) return 0;
        uint8_t after = 0;
    if (!fc26_live_copy(address, &after, 1)) return 0;
        fprintf(out, "[fc26-gameplay] set %s after_bits=%#x %s\n", field, after,
                after == value ? "OK" : "FAILED");
        return after == value;
}

static int fc26_gameplay_apply_once(Fc26GameplayApply *config, bool *changed) {
    *changed = false;
    uint64_t object = 0;
    const char *p = config->entries;
    if (!fc26_gameplay_object_current(config->base, &object)) return 0;
    if (!fc26_gameplay_table_ready(config->base)) return 0;
    while (*p) {
        char name[160] = {0}, value[80] = {0};
        int consumed = 0;
        if (sscanf(p, "%159[^=]=%79[^,]%n", name, value, &consumed) != 2 || !name[0]) {   /* value stops at the comma */
            fprintf(config->out, "[fc26-gameplay] REFUSED malformed entry in FC26_GAMEPLAY_SET\n");
            return -1;
        }
        if (!fc26_gameplay_allowed(name)) {
            fprintf(config->out, "[fc26-gameplay] REFUSED set %s\n", name);
            return -1;
        }
        if ((value[0] != '0' && value[0] != '1') || value[1]) {
            fprintf(config->out, "[fc26-gameplay] REFUSED set %s invalid value\n", name);
            return -1;
        }
        uint8_t current = 0, desired = (uint8_t)(value[0] - '0');
        int state = fc26_gameplay_field_current(config->base, name, &current);
        if (state > 0) {
            uint64_t object_after_read = 0;
            if (!fc26_gameplay_object_current(config->base, &object_after_read)) state = 0;
        }
        if (state < 0) {
            fprintf(config->out, "[fc26-gameplay] REFUSED set %s\n", name);
            return -1;
        }
        if (!state) return 0;
        if (current != desired) {
            int write_state = fc26_gameplay_field_write(config->base, config->out, name, desired);
            if (write_state > 0) {
                uint64_t object_after_write = 0;
                if (!fc26_gameplay_object_current(config->base, &object_after_write)) write_state = 0;
            }
            if (write_state < 0) {
                fprintf(config->out, "[fc26-gameplay] REFUSED set %s\n", name);
                return -1;
            }
            if (!write_state) {
                fprintf(config->out, "[fc26-gameplay] retry set %s\n", name);
                return 0;
            }
            unsigned index = 0;
            while (index < 4 && strcmp(fc26_gameplay_allowed_fields[index], name)) index++;
            fprintf(config->out, "[fc26-gameplay] %s %s\n",
                    config->seen[index] ? "reapplied" : "applied", name);
            config->seen[index] = true;
            *changed = true;
        }
        p += consumed;
        if (*p == ',') p++;
        else if (*p) {
            fprintf(config->out, "[fc26-gameplay] REFUSED malformed entry in FC26_GAMEPLAY_SET\n");
            return -1;
        }
    }
    return 1;
}

static void *fc26_gameplay_apply_thread(void *argument) {
    Fc26GameplayApply *config = argument;
    while (!atomic_load(&config->stop)) {
        bool changed = false;
        if (fc26_gameplay_apply_once(config, &changed) < 0) break;
        struct timespec delay = {
            .tv_sec = (time_t)(config->interval_ms / 1000),
            .tv_nsec = (long)(config->interval_ms % 1000) * 1000000L
        };
        nanosleep(&delay, NULL);
    }
    return NULL;
}

static void fc26_gameplay_apply_start(void) {
    const char *entries = getenv("FC26_GAMEPLAY_SET");
    if (!entries || !*entries) return;
    static Fc26GameplayApply config;
    config.base = runtime_module_base("main");
    config.out = stderr;
    config.entries = entries;
    config.interval_ms = 5000;
    atomic_init(&config.stop, false);
    pthread_t thread;
    if (pthread_create(&thread, NULL, fc26_gameplay_apply_thread, &config))
        fprintf(stderr, "[fc26-gameplay] REFUSED to start FC26_GAMEPLAY_SET thread\n");
    else pthread_detach(thread);
}
