#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include "fc26_force_present_interval.h"
int main(int argc, char **argv) {
    (void)argv;
    unsigned expected = argc > 1 ? 1u : 2u;
    if (fc26_effective_present_interval(2) != expected) return 1;
    if (fc26_effective_present_interval(0) != 1u) return 2;
    /* Environment is read once, not once per frame. */
    setenv("FC26_FPS60", argc > 1 ? "0" : "1", 1);
    if (fc26_effective_present_interval(2) != expected) return 3;
    return 0;
}
