/* Shared location of the original runtime, including launches of a copied app. */
#ifndef FC26_RUNTIME_EXECUTABLE_H
#define FC26_RUNTIME_EXECUTABLE_H
#include <mach-o/dyld.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
static inline int fc26_runtime_executable(char *path, uint32_t *size) {
    const char *original = getenv("FC26_RUNTIME_EXECUTABLE");
    if (!original || !*original) return _NSGetExecutablePath(path, size);
    size_t needed = strlen(original) + 1;
    if (needed > *size) { *size = (uint32_t)needed; return -1; }
    memcpy(path, original, needed);
    return 0;
}
#endif
