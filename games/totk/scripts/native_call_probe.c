/* Hardware test of the synthetic prepared-call window with real Darwin TSD.
 * No game entry is executed. Four pthreads use two different host callees.
 */
#include <libkern/OSCacheControl.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>

#if !defined(__APPLE__) || !defined(__aarch64__)
#error Apple silicon required
#endif

typedef uint64_t (*Function)(uint64_t, uint64_t, uint64_t, uint64_t);
static pthread_key_t target_key;
static Function caller;
static uintptr_t return_pc;
static atomic_uint errors;
static atomic_uint completed;

static void need(int ok, const char *message) {
    if (!ok) { fprintf(stderr, "%s\n", message); exit(1); }
}
__attribute__((noinline)) static uint64_t first(uint64_t a, uint64_t b, uint64_t c, uint64_t d) {
    if ((uintptr_t)__builtin_return_address(0) != return_pc) atomic_fetch_add(&errors, 1);
    return (a ^ UINT64_C(0x123456789abcdef0)) + b * 3 + c + d;
}
__attribute__((noinline)) static uint64_t second(uint64_t a, uint64_t b, uint64_t c, uint64_t d) {
    if ((uintptr_t)__builtin_return_address(0) != return_pc) atomic_fetch_add(&errors, 1);
    return (a + b) ^ (c * 7 + d);
}
static void *worker(void *argument) {
    uint64_t rng = (uintptr_t)argument + 1;
    for (unsigned i = 0; i < 5000; ++i) {
        rng = rng * UINT64_C(6364136223846793005) + 1;
        uint64_t a = rng, b = rng ^ 71, c = rng + 97, d = rng * 5;
        Function function = i & 1 ? second : first;
        if (pthread_setspecific(target_key, (void *)(uintptr_t)function)) { atomic_fetch_add(&errors, 1); break; }
        uintptr_t tsd;
        __asm__ volatile("mrs %0,tpidrro_el0" : "=r"(tsd));
        // Fail rather than execute code against an unexpected TSD layout.
        if (!tsd || (tsd & 7) || ((uintptr_t *)tsd)[target_key] != (uintptr_t)function) {
            atomic_fetch_add(&errors, 1); break;
        }
        uint64_t expected = i & 1 ? ((a + b) ^ (c * 7 + d)) :
            ((a ^ UINT64_C(0x123456789abcdef0)) + b * 3 + c + d);
        if (caller(a, b, c, d) != expected) atomic_fetch_add(&errors, 1);
        atomic_fetch_add(&completed, 1);
    }
    return NULL;
}
int main(int argc, char **argv) {
    need(argc == 2, "usage: native_call_probe fixture.bin");
    unsigned char *image = mmap(NULL, 0xC000, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
    need(image != MAP_FAILED, "mmap failed");
    FILE *f = fopen(argv[1], "rb");
    need(f != NULL && fread(image, 1, 0xC000, f) == 0xC000, "fixture read failed");
    fclose(f);
    need(pthread_key_create(&target_key, NULL) == 0, "pthread key creation failed");
    *(uint64_t *)(void *)(image + 0x4000) = (uint64_t)target_key * 8;
    caller = (Function)(void *)(image + 0x100);
    return_pc = (uintptr_t)image + 0x118;
    sys_icache_invalidate(image, 0x4000);
    need(mprotect(image, 0x4000, PROT_READ | PROT_EXEC) == 0, "executable protection failed");
    need(mprotect(image + 0x4000, 0x4000, PROT_READ) == 0, "key-page protection failed");
    pthread_t threads[4];
    for (uintptr_t i = 0; i < 4; ++i) need(pthread_create(&threads[i], NULL, worker, (void *)i) == 0, "thread creation failed");
    for (unsigned i = 0; i < 4; ++i) need(pthread_join(threads[i], NULL) == 0, "thread join failed");
    unsigned failures = atomic_load(&errors);
    unsigned calls = atomic_load(&completed);
    if (calls != 20000) ++failures;
    printf("{\"status\":\"%s\",\"threads\":4,\"completed_calls\":%u,\"errors\":%u,"
           "\"scope\":\"synthetic prepared-call window, real Darwin TSD and return-address checks\"}\n",
           failures ? "fail" : "pass", calls, failures);
    pthread_key_delete(target_key);
    munmap(image, 0xC000);
    return failures ? 1 : 0;
}
