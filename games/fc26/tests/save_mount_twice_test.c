/* FC 26 finds its saves again across boots (tests/test_save_mount_twice.py). The game's EASaveLoad (main+0x76d1ec0) lists
   save:/, and for each save folder mounts "save" once more (main+0x76d2fa0: EnsureSaveData, MountSaveData) before it
   reads <folder>/name. It takes 0, 0xe02 or 0x7802 (fs::ResultMountNameAlreadyExists) as "mounted"; any other result
   skips the folder. This harness plays that sequence on the real runtime/fs_host.c with a profile holding one save
   folder from a previous boot, and prints what the game would see.
   Usage: save_mount_twice_test <profile dir>   (exit 0: the earlier save's name was read back) */
#include "runtime.h"
#include "fs_host.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

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
static int accepted(unsigned r) { return r == 0 || r == 0xe02u || r == 0x7802u; }   /* main+0x76d30c8..0x76d30e0 */

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    setenv("TOTK_PROFILE_DIR", argv[1], 1);
    uint64_t uid[2]; runtime_account_uid(uid);
    unsigned (*ensure)(const uint64_t *) = FN(unsigned (*)(const uint64_t *), "_ZN2nn2fs14EnsureSaveDataERKNS_7account3UidE");
    unsigned (*mount)(const char *, const uint64_t *) = FN(unsigned (*)(const char *, const uint64_t *), "_ZN2nn2fs13MountSaveDataEPKcRKNS_7account3UidE");
    unsigned (*entry_type)(int *, const char *) = FN(unsigned (*)(int *, const char *), "_ZN2nn2fs12GetEntryTypeEPNS0_18DirectoryEntryTypeEPKc");
    unsigned (*open_file)(uint64_t *, const char *, int) = FN(unsigned (*)(uint64_t *, const char *, int), "_ZN2nn2fs8OpenFileEPNS0_10FileHandleEPKci");
    unsigned (*read_file)(uint64_t *, uint64_t, int64_t, void *, size_t) = FN(unsigned (*)(uint64_t *, uint64_t, int64_t, void *, size_t), "_ZN2nn2fs8ReadFileEPmNS0_10FileHandleElPvm");
    void (*close_file)(uint64_t) = FN(void (*)(uint64_t), "_ZN2nn2fs9CloseFileENS0_10FileHandleE");
    if (!ensure || !mount || !entry_type || !open_file || !read_file || !close_file) { puts("FAIL: an fs override is missing"); return 1; }

    unsigned r = ensure(uid);
    printf("EnsureSaveData = %#x\n", r);
    r = mount("save", uid);
    printf("first MountSaveData(\"save\") = %#x\n", r);
    if (r) return 1;
    /* The folder list the game got from save:/ (written by the test before this run): for each one, mount again. */
    r = ensure(uid);
    unsigned again = mount("save", uid);
    printf("MountSaveData(\"save\") while mounted = %#x (%s)\n", again, accepted(again) ? "the game goes on to read the name" : "the game skips the save");
    if (!accepted(r) || !accepted(again)) return 1;
    int type = -1;
    r = entry_type(&type, "save:/7f9bb0a4/name");
    if (r || type != 1) { printf("FAIL: GetEntryType name = %#x type %d\n", r, type); return 1; }
    uint64_t h = 0, got = 0; char name[64] = {0};
    if ((r = open_file(&h, "save:/7f9bb0a4/name", 1)) || (r = read_file(&got, h, 0, name, sizeof name - 1))) { printf("FAIL: name read %#x\n", r); return 1; }
    close_file(h);
    printf("save found: %s\n", name);
    return 0;
}
