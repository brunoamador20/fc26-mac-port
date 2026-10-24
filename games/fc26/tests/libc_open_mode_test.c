/* FC 26 creates its cache and EA files with libc open(path, O_CREAT, mode) (tests/test_libc_open_mode.py). The game is
   built for the Switch ABI, where the mode of a variadic call travels in w2 like a fixed argument; a host function
   declared variadic reads it from the stack on macOS instead, so files were created with whatever was there
   (040, 0200, 0350, 0: profile files the next boot could not read). This harness calls the real runtime/fs_host.c
   override the way the game does, through a three-argument pointer, and checks the mode on disk. A file an earlier
   build left unreadable must open again: on the Switch a save file has no permission bits.
   Usage: libc_open_mode_test <profile dir>   (exit 0: 0640 on disk and the unreadable file was read) */
#include "runtime.h"
#include "fs_host.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <dirent.h>

pthread_key_t runtime_keys[8];
void *runtime_symbol(const char *name) { (void)name; return NULL; }
void hle_signal_system_event(void *ev) { (void)ev; }
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

int runtime_romfs_owns(const char *path) { (void)path; return 0; }
int runtime_romfs_handle(uint64_t h) { (void)h; return 0; }
unsigned runtime_romfs_open(uint64_t *out, const char *path, int mode) { (void)out; (void)path; (void)mode; return 1; }
unsigned runtime_romfs_read(uint64_t *out, uint64_t h, int64_t offset, void *buffer, uint64_t size) { (void)out; (void)h; (void)offset; (void)buffer; (void)size; return 1; }
unsigned runtime_romfs_size(int64_t *out, uint64_t h) { (void)out; (void)h; return 1; }
void runtime_romfs_close(uint64_t h) { (void)h; }
unsigned runtime_romfs_entry_type(int *out, const char *path) { (void)out; (void)path; return 1; }
unsigned runtime_romfs_list(const char *path, int mode, void (*add)(void *ctx, const char *name, int is_dir, int64_t size), void *ctx) {
    (void)path; (void)mode; (void)add; (void)ctx; return 1;
}
int runtime_romfs_is_mounted(const char *name) {
    return name && !strcmp(name, "rom");
}
int runtime_romfs_unmount(const char *name) { (void)name; return 0; }

#define FN(type, name) ((type)runtime_fs_host_override(name))
#define GUEST_O_RDONLY 00
#define GUEST_O_WRONLY 01
#define GUEST_O_CREAT 0100
#define GUEST_O_TRUNC 01000

/* Leaves non-zero junk where a variadic callee would look for the mode. */
/* <profile>/save/<user folder>: the one folder MountSaveData made. */
static int save_root(const char *profile, char *out, size_t n) {
    char dir[1024]; snprintf(dir, sizeof dir, "%s/save", profile);
    DIR *d = opendir(dir); struct dirent *e; int found = 0;
    while (d && (e = readdir(d))) if (e->d_name[0] != '.') { snprintf(out, n, "%s/%s", dir, e->d_name); found = 1; }
    if (d) closedir(d);
    return found;
}

static __attribute__((noinline)) int call_open(int (*open_fn)(const char *, int, int), const char *path, int flags, int mode) {
    volatile uint32_t junk[64]; for (int i = 0; i < 64; i++) junk[i] = 0x5a5a5a5a;
    (void)junk; return open_fn(path, flags, mode);
}

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    setenv("TOTK_PROFILE_DIR", argv[1], 1);
    umask(0);
    uint64_t uid[2]; runtime_account_uid(uid);
    unsigned (*ensure)(const uint64_t *) = FN(unsigned (*)(const uint64_t *), "_ZN2nn2fs14EnsureSaveDataERKNS_7account3UidE");
    unsigned (*mount)(const char *, const uint64_t *) = FN(unsigned (*)(const char *, const uint64_t *), "_ZN2nn2fs13MountSaveDataEPKcRKNS_7account3UidE");
    int (*open_fn)(const char *, int, int) = FN(int (*)(const char *, int, int), "open");
    ssize_t (*read_fn)(int, void *, size_t) = FN(ssize_t (*)(int, void *, size_t), "read");
    ssize_t (*write_fn)(int, const void *, size_t) = FN(ssize_t (*)(int, const void *, size_t), "write");
    int (*close_fn)(int) = FN(int (*)(int), "close");
    if (!ensure || !mount || !open_fn || !read_fn || !write_fn || !close_fn) { puts("FAIL: an override is missing"); return 1; }
    if (ensure(uid) || mount("save", uid)) { puts("FAIL: mount"); return 1; }

    int fd = call_open(open_fn, "save:/created.json", GUEST_O_WRONLY | GUEST_O_CREAT | GUEST_O_TRUNC, 0640);
    if (fd < 0) { puts("FAIL: open with O_CREAT"); return 1; }
    write_fn(fd, "{}", 2); close_fn(fd);
    char root[1200], host[2048]; if (!save_root(argv[1], root, sizeof root)) { puts("FAIL: no save folder"); return 1; }
    snprintf(host, sizeof host, "%s/created.json", root);
    struct stat st; if (stat(host, &st)) { printf("FAIL: %s not on disk\n", host); return 1; }
    printf("created mode %04o (want 0640)\n", (unsigned)(st.st_mode & 07777));

    /* What an earlier build left: a profile file without the owner's read bit. */
    snprintf(host, sizeof host, "%s/old.json", root);
    FILE *f = fopen(host, "w"); if (!f) { puts("FAIL: seed"); return 1; } fputs("old", f); fclose(f); chmod(host, 0200);
    char buf[8] = {0}; fd = call_open(open_fn, "save:/old.json", GUEST_O_RDONLY, 0);
    ssize_t got = fd < 0 ? -1 : read_fn(fd, buf, sizeof buf - 1); if (fd >= 0) close_fn(fd);
    printf("unreadable file: open %s, read \"%s\"\n", fd < 0 ? "failed" : "ok", buf);
    return (st.st_mode & 07777) == 0640 && got == 3 && !strcmp(buf, "old") ? 0 : 1;
}
