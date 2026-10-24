/* Behavioral tests for libc filesystem overrides in FC 26:
   open, fstat, read, lseek, close, stat, write, ftruncate, unlink, mkdir, rmdir. */
#include "runtime.h"
#include "fs_host.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <stddef.h>

struct guest_stat {
    uint64_t st_dev;
    uint64_t st_ino;
    uint32_t st_mode;
    uint32_t st_nlink;
    uint32_t st_uid;
    uint32_t st_gid;
    uint64_t st_rdev;
    uint64_t __pad;
    int64_t  st_size;
    int32_t  st_blksize;
    int32_t  __pad2;
    int64_t  st_blocks;
    int64_t  st_atime_sec;
    int64_t  st_atime_nsec;
    int64_t  st_mtime_sec;
    int64_t  st_mtime_nsec;
    int64_t  st_ctime_sec;
    int64_t  st_ctime_nsec;
    uint32_t unused[2];
};
_Static_assert(sizeof(struct guest_stat) == 128, "guest_stat size");
_Static_assert(offsetof(struct guest_stat, st_mode) == 16, "guest_stat st_mode offset");
_Static_assert(offsetof(struct guest_stat, st_size) == 48, "guest_stat st_size offset");

pthread_key_t runtime_keys[8];
/* The sdk's own libc, as runtime_symbol finds it: only close is exported here, to see a descriptor that is not ours
   reach it (and not the host); read is missing, to see EBADF. */
static int sdk_close_calls, sdk_close_fd = -1;
static int fake_sdk_close(int fd) { sdk_close_calls++; sdk_close_fd = fd; return 0; }
void *runtime_symbol(const char *name) { return !strcmp(name, "close") ? (void *)fake_sdk_close : NULL; }
void hle_clear_system_event(void *ev) { (void)ev; }
void hle_signal_system_event(void *ev) { (void)ev; }   /* account.c: the async contexts signal their event (threads.c in the runtime) */
static int guest_errno(void) { int v; memcpy(&v, (uint8_t *)pthread_getspecific(runtime_keys[2]) + 0x1d8, sizeof v); return v; }
static void *objects[64];
static int kinds[64];
static unsigned nobjects;
uint32_t runtime_handle_new(int session, void *obj) {
    if (nobjects == 64) runtime_fail("test handle table full");
    objects[nobjects] = obj; kinds[nobjects] = session;
    return 0x100 + nobjects++;
}
void *runtime_handle_get(uint32_t h, int session) { h -= 0x100; return h < nobjects && kinds[h] == session ? objects[h] : NULL; }
void *runtime_handle_take_session(uint32_t h) { void *s = runtime_handle_get(h, 1); if (s) objects[h - 0x100] = NULL; return s; }
void runtime_trace_guest(uint64_t fp, uint64_t lr) { (void)fp; (void)lr; }
uint64_t runtime_desired_language(void) { uint64_t v = 0; memcpy(&v, "en-US", 5); return v; }
uint32_t runtime_event_new(void) { return runtime_handle_new(2, (void *)1); }
uint32_t runtime_event_readable(uint32_t w) { return w; }
void runtime_event_signal(uint32_t w) { (void)w; }

void *runtime_hid_feedback_override(const char *name) { (void)name; return NULL; }
int runtime_handheld_mode(void) { return 0; }
void runtime_autoload_user_input(void) {}
void runtime_autoload_save_file_opened(void) {}
void dm_guest_write_prepare(void *addr, size_t size) { (void)addr; (void)size; }
void runtime_fs_log(const char *what, const char *path) { (void)what; (void)path; }
uint64_t runtime_now_ns(void) { return 0; }

static const char s_fake_rom_content[] = "[AI]\nName=AI\nSize=12345\n";

int runtime_romfs_owns(const char *path) {
    return path && !strncmp(path, "rom:", 4);
}
int runtime_romfs_handle(uint64_t h) {
    return h == 0x100000001ULL;
}
unsigned runtime_romfs_open(uint64_t *out, const char *path, int mode) {
    if (!path || strcmp(path, "rom:/Scripts/BootIni/MemoryInit.ini") != 0 || mode != 1) return 1;
    *out = 0x100000001ULL;
    return 0;
}
unsigned runtime_romfs_read(uint64_t *out, uint64_t h, int64_t offset, void *buffer, uint64_t size) {
    if (h != 0x100000001ULL || offset < 0) return 1;
    size_t total = sizeof(s_fake_rom_content) - 1;
    if ((size_t)offset >= total) { *out = 0; return 0; }
    size_t avail = total - (size_t)offset;
    size_t to_copy = size < avail ? size : avail;
    memcpy(buffer, s_fake_rom_content + offset, to_copy);
    *out = to_copy;
    return 0;
}
unsigned runtime_romfs_size(int64_t *out, uint64_t h) {
    if (h != 0x100000001ULL) return 1;
    *out = (int64_t)(sizeof(s_fake_rom_content) - 1);
    return 0;
}
void runtime_romfs_close(uint64_t h) { (void)h; }
unsigned runtime_romfs_entry_type(int *out, const char *path) {
    if (path && !strcmp(path, "rom:/Scripts/BootIni/MemoryInit.ini")) {
        *out = 1;
        return 0;
    }
    return 1;
}
unsigned runtime_romfs_list(const char *path, int mode, void (*add)(void *ctx, const char *name, int is_dir, int64_t size), void *ctx) {
    (void)path; (void)mode; (void)add; (void)ctx; return 1;
}
int runtime_romfs_is_mounted(const char *name) {
    return name && !strcmp(name, "rom");
}
int runtime_romfs_unmount(const char *name) { (void)name; return 0; }

int main(void) {
    if (!getenv("TOTK_PROFILE_DIR")) setenv("TOTK_PROFILE_DIR", "/tmp/fc26_libc_fs_test_profile", 1);
    /* The guest thread's ThreadLocalRegion, as loader.c sets slot KTLR (runtime_keys[2]): the game's errno is at +0x1d8. */
    for (int i = 0; i < 8; i++) assert(pthread_key_create(&runtime_keys[i], NULL) == 0);
    static uint8_t tlr[0x200];
    assert(pthread_setspecific(runtime_keys[2], tlr) == 0);

    int (*g_open)(const char *, int, ...) = (int (*)(const char *, int, ...))runtime_fs_host_override("open");
    int (*g_close)(int) = (int (*)(int))runtime_fs_host_override("close");
    ssize_t (*g_read)(int, void *, size_t) = (ssize_t (*)(int, void *, size_t))runtime_fs_host_override("read");
    ssize_t (*g_write)(int, const void *, size_t) = (ssize_t (*)(int, const void *, size_t))runtime_fs_host_override("write");
    off_t (*g_lseek)(int, off_t, int) = (off_t (*)(int, off_t, int))runtime_fs_host_override("lseek");
    int (*g_fstat)(int, struct guest_stat *) = (int (*)(int, struct guest_stat *))runtime_fs_host_override("fstat");
    int (*g_stat)(const char *, struct guest_stat *) = (int (*)(const char *, struct guest_stat *))runtime_fs_host_override("stat");
    int (*g_unlink)(const char *) = (int (*)(const char *))runtime_fs_host_override("unlink");
    unsigned (*mount_temp)(const char *) = (unsigned (*)(const char *))runtime_fs_host_override("_ZN2nn2fs21MountTemporaryStorageEPKc");

    assert(g_open != NULL);
    assert(g_close != NULL);
    assert(g_read != NULL);
    assert(g_write != NULL);
    assert(g_lseek != NULL);
    assert(g_fstat != NULL);
    assert(g_stat != NULL);
    assert(g_unlink != NULL);
    assert(mount_temp != NULL);

    /* 1. Unknown mount must fail with ENOENT */
    errno = 0;
    int bad_fd = g_open("unknown:/file.txt", 0);
    assert(bad_fd == -1);
    assert(errno == ENOENT);
    assert(guest_errno() == ENOENT);

    /* 2. Write open on RomFS must fail with EROFS */
    errno = 0;
    bad_fd = g_open("rom:/Scripts/BootIni/MemoryInit.ini", 1); /* O_WRONLY */
    assert(bad_fd == -1);
    assert(errno == EROFS);
    assert(guest_errno() == EROFS);

    /* 2b. A descriptor below 0x10000 that is not stdio is not the host's: close goes to the sdk's close and the
       host fd stays open; read (not exported by the fake sdk) fails with EBADF; close(2) keeps the runtime's stderr. */
    int host_fd = open("/dev/null", O_RDONLY);
    assert(host_fd > 2 && host_fd < 0x10000);
    assert(g_close(host_fd) == 0);
    assert(sdk_close_calls == 1 && sdk_close_fd == host_fd);
    assert(fcntl(host_fd, F_GETFD) != -1);
    char one;
    assert(g_read(host_fd, &one, 1) == -1);
    assert(guest_errno() == EBADF);
    close(host_fd);
    assert(g_close(2) == 0);
    assert(fcntl(2, F_GETFD) != -1);
    assert(sdk_close_calls == 1);

    /* 3. Read open on RomFS must succeed and return guest fd in range >= 0x10000 */
    int rom_fd = g_open("rom:/Scripts/BootIni/MemoryInit.ini", 0); /* O_RDONLY */
    assert(rom_fd >= 0x10000);

    /* 4. fstat on rom_fd must fill guest_stat with correct st_size (at offset 48) */
    struct guest_stat gst;
    memset(&gst, 0, sizeof(gst));
    assert(g_fstat(rom_fd, &gst) == 0);
    assert(gst.st_size == (int64_t)(sizeof(s_fake_rom_content) - 1));
    assert((gst.st_mode & 0170000) == 0100000); /* S_IFREG */

    /* 5. read from rom_fd */
    char buf[64] = {0};
    ssize_t n = g_read(rom_fd, buf, sizeof(buf));
    assert(n == (ssize_t)(sizeof(s_fake_rom_content) - 1));
    assert(strcmp(buf, s_fake_rom_content) == 0);

    /* EOF check */
    n = g_read(rom_fd, buf, sizeof(buf));
    assert(n == 0);

    /* lseek back to 0 and read again */
    off_t off = g_lseek(rom_fd, 0, SEEK_SET);
    assert(off == 0);
    memset(buf, 0, sizeof(buf));
    n = g_read(rom_fd, buf, 4);
    assert(n == 4);
    assert(memcmp(buf, "[AI]", 4) == 0);

    /* close rom_fd */
    assert(g_close(rom_fd) == 0);

    /* 6. stat on RomFS file */
    memset(&gst, 0, sizeof(gst));
    assert(g_stat("rom:/Scripts/BootIni/MemoryInit.ini", &gst) == 0);
    assert(gst.st_size == (int64_t)(sizeof(s_fake_rom_content) - 1));

    /* 7. Host storage mount (temp) */
    assert(mount_temp("tmp") == 0);

    /* open with O_CREAT | O_WRONLY */
    int tmp_fd = g_open("tmp:/test_libc.txt", 0100 | 01, 0644);
    assert(tmp_fd >= 0x10000);
    const char msg[] = "Hello FC26 libc fs!";
    assert(g_write(tmp_fd, msg, strlen(msg)) == (ssize_t)strlen(msg));
    assert(g_close(tmp_fd) == 0);

    /* stat on created file */
    memset(&gst, 0, sizeof(gst));
    assert(g_stat("tmp:/test_libc.txt", &gst) == 0);
    assert(gst.st_size == (int64_t)strlen(msg));

    /* open for read, fstat, read, close */
    tmp_fd = g_open("tmp:/test_libc.txt", 0);
    assert(tmp_fd >= 0x10000);
    memset(&gst, 0, sizeof(gst));
    assert(g_fstat(tmp_fd, &gst) == 0);
    assert(gst.st_size == (int64_t)strlen(msg));
    memset(buf, 0, sizeof(buf));
    assert(g_read(tmp_fd, buf, sizeof(buf)) == (ssize_t)strlen(msg));
    assert(strcmp(buf, msg) == 0);
    assert(g_close(tmp_fd) == 0);

    /* unlink */
    assert(g_unlink("tmp:/test_libc.txt") == 0);
    assert(g_stat("tmp:/test_libc.txt", &gst) == -1);
    assert(errno == ENOENT);

    printf("ALL_LIBC_FS_OVERRIDES_OK\n");
    return 0;
}
