/* Multi-mount RomFS test: verifies multiple mount names (e.g. "rom", "eadpsdk_rom", "third"),
   content equivalence, unmount behavior, unmounted isolation, and table fullness. */
#include "runtime.h"
#include "fs_host.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <stdarg.h>

void runtime_boot_progress(const char *stage, uint64_t done, uint64_t total) { (void)stage; (void)done; (void)total; }
void runtime_boot_status(const char *title, const char *subtitle) { (void)title; (void)subtitle; }
void dm_guest_write_prepare(void *addr, size_t size) { (void)addr; (void)size; }
uint64_t runtime_now_ns(void) { return 0; }
void *runtime_fs_host_override(const char *name) { (void)name; return NULL; }
int runtime_output_res(unsigned *w, unsigned *h) { if (w) *w = 1920; if (h) *h = 1080; return 0; }
uint64_t runtime_output_res_extra_bytes(void) { return 0; }

_Noreturn void runtime_fail(const char *message) {
    fprintf(stderr, "runtime_fail: %s\n", message);
    exit(42);
}

void runtime_missing(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fprintf(stderr, "\n");
}

int main(int argc, char **argv) {
    const char *mode = argc > 1 ? argv[1] : "basic";
    unsigned (*mount_rom)(const char *, void *, uint64_t) =
        (unsigned (*)(const char *, void *, uint64_t))runtime_fs_override("_ZN2nn2fs8MountRomEPKcPvm");
    assert(mount_rom != NULL);

    if (!strcmp(mode, "basic")) {
        /* 1. Mount "rom" */
        assert(mount_rom("rom", NULL, 0) == 0);
        assert(runtime_romfs_is_mounted("rom") == 1);
        assert(runtime_romfs_owns("rom:/Data/layout.toc") == 1);

        uint64_t h1 = 0;
        assert(runtime_romfs_open(&h1, "rom:/Data/layout.toc", 1) == 0);
        char buf1[256];
        uint64_t n1 = 0;
        assert(runtime_romfs_read(&n1, h1, 0, buf1, sizeof(buf1)) == 0);
        assert(n1 > 0);
        runtime_romfs_close(h1);

        /* 2. Mount second name "eadpsdk_rom" */
        assert(mount_rom("eadpsdk_rom", NULL, 0) == 0);
        assert(runtime_romfs_is_mounted("eadpsdk_rom") == 1);
        assert(runtime_romfs_owns("eadpsdk_rom:/Data/layout.toc") == 1);

        uint64_t h2 = 0;
        assert(runtime_romfs_open(&h2, "eadpsdk_rom:/Data/layout.toc", 1) == 0);
        char buf2[256];
        uint64_t n2 = 0;
        assert(runtime_romfs_read(&n2, h2, 0, buf2, sizeof(buf2)) == 0);
        assert(n2 == n1);
        assert(memcmp(buf1, buf2, n1) == 0);
        runtime_romfs_close(h2);

        /* Mounting same name twice is accepted */
        assert(mount_rom("eadpsdk_rom", NULL, 0) == 0);

        /* 3. Mount third name "third_rom" */
        assert(mount_rom("third_rom", NULL, 0) == 0);
        assert(runtime_romfs_is_mounted("third_rom") == 1);
        assert(runtime_romfs_owns("third_rom:/Data/layout.toc") == 1);

        uint64_t h3 = 0;
        assert(runtime_romfs_open(&h3, "third_rom:/Data/layout.toc", 1) == 0);
        char buf3[256];
        uint64_t n3 = 0;
        assert(runtime_romfs_read(&n3, h3, 0, buf3, sizeof(buf3)) == 0);
        assert(n3 == n1);
        assert(memcmp(buf1, buf3, n1) == 0);
        runtime_romfs_close(h3);

        /* 4. Unmounted name remains outside (owns == 0) */
        assert(runtime_romfs_is_mounted("unmounted") == 0);
        assert(runtime_romfs_owns("unmounted:/Data/layout.toc") == 0);
        uint64_t hu = 0;
        assert(runtime_romfs_open(&hu, "unmounted:/Data/layout.toc", 1) != 0);

        /* 5. Unmount removes only the target name */
        assert(runtime_romfs_unmount("third_rom") == 1);
        assert(runtime_romfs_is_mounted("third_rom") == 0);
        assert(runtime_romfs_owns("third_rom:/Data/layout.toc") == 0);
        assert(runtime_romfs_is_mounted("rom") == 1);
        assert(runtime_romfs_is_mounted("eadpsdk_rom") == 1);
        assert(runtime_romfs_unmount("unmounted") == 0);

        printf("ROMFS_MULTI_MOUNT_BASIC_OK\n");
        return 0;
    }

    if (!strcmp(mode, "full")) {
        /* Mount 8 distinct names to fill table, 9th must fail */
        assert(mount_rom("m0", NULL, 0) == 0);
        assert(mount_rom("m1", NULL, 0) == 0);
        assert(mount_rom("m2", NULL, 0) == 0);
        assert(mount_rom("m3", NULL, 0) == 0);
        assert(mount_rom("m4", NULL, 0) == 0);
        assert(mount_rom("m5", NULL, 0) == 0);
        assert(mount_rom("m6", NULL, 0) == 0);
        assert(mount_rom("m7", NULL, 0) == 0);

        /* 9th mount must trigger table full failure */
        fprintf(stderr, "attempting 9th mount...\n");
        mount_rom("m8", NULL, 0);
        return 0; /* should not reach here if runtime_fail exits */
    }

    return 1;
}
