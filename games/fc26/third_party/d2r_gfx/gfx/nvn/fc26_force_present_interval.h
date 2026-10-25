#pragma once
#include <stdlib.h>
#include <string.h>
#include <pthread.h>

/* Immutable process preference. No environment lookup on the per-frame path. */
static pthread_once_t fc26_interval_once = PTHREAD_ONCE_INIT;
static int fc26_interval_enabled;
static void fc26_interval_init(void) {
    const char *e = getenv("FC26_FPS60");
    const char *diagnostic = getenv("FC26_FORCE_PRESENT_INTERVAL");
    fc26_interval_enabled = (e && !strcmp(e, "1")) ||
        (diagnostic && !strcmp(diagnostic, "1"));
}
static inline int fc26_force_present_interval_enabled(void) {
    pthread_once(&fc26_interval_once, fc26_interval_init);
    return fc26_interval_enabled;
}
static inline unsigned fc26_effective_present_interval(int requested) {
    if (fc26_force_present_interval_enabled()) return 1u;
    return requested <= 0 ? 1u : (unsigned)requested;
}
