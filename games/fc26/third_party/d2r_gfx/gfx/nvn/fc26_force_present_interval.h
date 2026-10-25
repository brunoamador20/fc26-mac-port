#pragma once

static inline int fc26_force_present_interval_enabled(void) {
    const char *forced = getenv("FC26_FORCE_PRESENT_INTERVAL");
    return forced && !strcmp(forced, "1");
}

static inline unsigned fc26_effective_present_interval(int requested) {
    if (fc26_force_present_interval_enabled()) return 1u;
    return requested <= 0 ? 1u : (unsigned)requested;
}
