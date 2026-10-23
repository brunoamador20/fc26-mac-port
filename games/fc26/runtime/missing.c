/* How the runtime stops. runtime_fail ends the process with "[totk] FAIL: <message>". A stop on something the host does not
   have yet also writes one line "[fc26-missing] <what>" so `grep '\[fc26-missing\]' <log>` lists what the game needs:
   runtime_missing writes it with the name and number (service, command, port, import, SVC, GetInfo id, ...); a stop that
   gave none and says it lacks something ("not (yet) implemented", "not supported", ...) gets a generic one. Portable C (tests use it). */
#include "runtime.h"
#include <stdarg.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static _Atomic int missing_written;

void runtime_missing(const char *format, ...) {
    va_list args;
    va_start(args, format);
    char line[512];
    vsnprintf(line, sizeof line, format, args);
    va_end(args);
    fprintf(stderr, "[fc26-missing] %s\n", line);
    atomic_store(&missing_written, 1);
}

_Noreturn void runtime_fail(const char *message) {
    fprintf(stderr, "[totk] FAIL: %s\n", message);
    static const char *const lacks[] = {"not implemented", "not yet implemented", "unimplemented", "not supported", "unsupported", "not mapped"};
    int missing = 0;
    for (size_t i = 0; i < sizeof lacks / sizeof *lacks; i++) missing |= strstr(message, lacks[i]) != NULL;
    if (missing && !atomic_load(&missing_written)) fprintf(stderr, "[fc26-missing] runtime: %s\n", message);
    exit(1);
}
