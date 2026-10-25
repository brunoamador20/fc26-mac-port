#include <stdlib.h>
#include <stdio.h>
#include <string.h>

#define R_IMPL extern
#include "fc26_force_present_interval.h"

typedef struct { int interval; } Window;

static unsigned window_ticks(const Window *window) {
    const char *forced = getenv("FC26_FORCE_PRESENT_INTERVAL");
    if (forced && !strcmp(forced, "1")) return 1u;
    return window->interval <= 0 ? 1u : (unsigned)window->interval;
}

int main(void) {
    const char *forced = getenv("FC26_FORCE_PRESENT_INTERVAL");
    unsigned requested = forced && !strcmp(forced, "1") ? 1u : 2u;

    unsetenv("FC26_FORCE_PRESENT_INTERVAL");
    if (fc26_effective_present_interval(2) != 2u) return 1;
    if (fc26_effective_present_interval(0) != 1u) return 2;

    setenv("FC26_FORCE_PRESENT_INTERVAL", "1", 1);
    Window window = {2};
    if (window_ticks(&window) != 1u) return 3;

    if (fc26_effective_present_interval(requested) != 1u) return 3;
    if (fc26_effective_present_interval(2) != 1u) return 4;

    printf("present interval: requested=%u\n", requested);
    return 0;
}
