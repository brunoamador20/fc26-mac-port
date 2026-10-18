/* Run the exact rewritten 1.4.3 cold-retry windows on Darwin hardware.
   Read-only source mapping; COW exit words turn the isolated window into a
   callable CAS. No game entry, file mutation, GPU work or save access. */
#include <assert.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <libkern/OSCacheControl.h>

extern uint32_t invoke_window_1(void *, void *, uint32_t);
extern void invoke_window_2(void *, void *, uint32_t, uint32_t);
__asm__(
".text\n.p2align 2\n"
"_invoke_window_1:\n"
"stp x29,x30,[sp,#-16]!\nmov x29,sp\nmov x10,x1\nmov w15,w2\nblr x0\n"
"mov w0,w17\nldp x29,x30,[sp],#16\nret\n"
"_invoke_window_2:\n"
"stp x29,x30,[sp,#-16]!\nmov x29,sp\nmov x10,x1\nmov w16,w2\nmov w17,w3\nblr x0\n"
"ldp x29,x30,[sp],#16\nret\n");

static pthread_key_t key18;
static _Atomic uint32_t cell;
static _Atomic uint64_t retries;
static void *entry;
static unsigned mode;
enum { THREADS = 8, INCREMENTS = 20000 };

static void *worker(void *unused) {
    (void)unused;
    assert(!pthread_setspecific(key18, (void *)(uintptr_t)0xdeadbeef));
    uint64_t local_retries = 0;
    for (unsigned i = 0; i < INCREMENTS; i++) {
        for (;;) {
            uint32_t expected = atomic_load_explicit(&cell, memory_order_relaxed);
            unsigned failed;
            if (mode == 1) failed = invoke_window_1(entry, &cell, expected);
            else {
                invoke_window_2(entry, &cell, expected, expected + 1);
                failed = (unsigned)(uintptr_t)pthread_getspecific(key18);
            }
            if (!failed) break;
            local_retries++;
        }
    }
    atomic_fetch_add(&retries, local_retries);
    return NULL;
}

static void run_case(uint8_t *image, size_t key_offset, unsigned key_index,
                     uint64_t head, uint64_t success, uint64_t mismatch, unsigned kind) {
    size_t page_size = (size_t)sysconf(_SC_PAGESIZE);
    uint64_t exits[] = {success, mismatch};
    for (unsigned i = 0; i < 2; i++) {
        uint8_t *page = image + (exits[i] & ~(page_size - 1));
        assert(!mprotect(page, page_size, PROT_READ | PROT_WRITE));
        uint32_t ret = 0xd65f03c0;
        memcpy(image + exits[i], &ret, sizeof ret);
        sys_icache_invalidate(image + exits[i], sizeof ret);
        assert(!mprotect(page, page_size, PROT_READ | PROT_EXEC));
    }
    assert(!mprotect(image + key_offset, page_size, PROT_READ | PROT_WRITE));
    memcpy(image + key_offset + key_index * 8, &(uint64_t){(uint64_t)key18 * 8}, 8);
    mode = kind; entry = image + head;
    atomic_store(&cell, 1); atomic_store(&retries, 0);
    pthread_t threads[THREADS];
    for (unsigned i = 0; i < THREADS; i++) assert(!pthread_create(&threads[i], NULL, worker, NULL));
    for (unsigned i = 0; i < THREADS; i++) assert(!pthread_join(threads[i], NULL));
    uint32_t result = atomic_load(&cell);
    assert(result == 1 + THREADS * INCREMENTS);
    printf("{\"status\":\"pass\",\"window\":\"0x%llx\",\"threads\":%u,\"increments\":%u,\"retries\":%llu,\"final\":%u}\n",
           (unsigned long long)head, THREADS, THREADS * INCREMENTS,
           (unsigned long long)atomic_load(&retries), result);
    fflush(stdout);
}

static uint64_t branch_target(uint8_t *image, uint64_t address) {
    uint32_t word; memcpy(&word, image + address, 4);
    assert((word & 0xfc000000u) == 0x14000000u);
    int32_t delta = ((int32_t)(word << 6)) >> 4;
    return address + delta;
}

int main(int argc, char **argv) {
    assert(argc == 4 || (argc == 5 && !strcmp(argv[4], "negative")));
    alarm(30);
    int fd = open(argv[1], O_RDONLY); assert(fd >= 0);
    struct stat st; assert(!fstat(fd, &st));
    size_t page_size = (size_t)sysconf(_SC_PAGESIZE);
    size_t size = ((size_t)st.st_size + page_size - 1) & ~(page_size - 1);
    uint8_t *image = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
    assert(image != MAP_FAILED);
    size_t done = 0;
    while (done < (size_t)st.st_size) {
        ssize_t got = read(fd, image + done, (size_t)st.st_size - done);
        assert(got > 0); done += (size_t)got;
    }
    close(fd);
    if (argc == 5) {
        uint64_t prologue = branch_target(image, 0x181ec);
        uint64_t body = branch_target(image, prologue + 24);
        uint32_t word; memcpy(&word, image + body + 12, 4);
        assert((word & 0x7f000000u) == 0x11000000u && ((word >> 10) & 0xfff) == 1);
        word -= 1 << 10; /* Broken CAS succeeds without incrementing the cell. */
        memcpy(image + body + 12, &word, 4);
    }
    sys_icache_invalidate(image, size);
    assert(!mprotect(image, size, PROT_READ | PROT_EXEC));
    size_t key_offset = strtoull(argv[2], NULL, 0);
    unsigned key_index = (unsigned)strtoul(argv[3], NULL, 0);
    assert(key_offset % page_size == 0 && key_offset + page_size <= size && key_index < 8);
    assert(!pthread_key_create(&key18, NULL) && key18 != 0);
    run_case(image, key_offset, key_index, 0x181ec, 0x18204, 0x185a4, 1);
    run_case(image, key_offset, key_index, 0x18238, 0x1824c, 0x18224, 2);
    pthread_key_delete(key18); munmap(image, size);
    return 0;
}
