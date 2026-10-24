/* Behavioral tests for the 9 new nn::fs host overrides in FC 26:
   DeleteDirectory, RenameDirectory, GetFreeSpaceSize, MountAddOnContent,
   MountCacheStorage(const char*), GetCacheStorageMax, GetCacheStorageSize,
   GetDirectoryEntryCount, QueryMountAddOnContentCacheSize. */
#include "runtime.h"
#include "fs_host.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <stdbool.h>

#define R_PATH_NOT_FOUND 0x202u
#define R_ALREADY_EXISTS 0x402u
#define R_NOT_EMPTY 0x1002u
#define R_TARGET_NOT_FOUND 0x7d402u
#define R_INVALID_ARGUMENT 0x2ee202u
#define R_INVALID_PATH 0x2ee602u

pthread_key_t runtime_keys[8];
void *runtime_symbol(const char *name) { (void)name; return NULL; }   /* fs_host.c: the sdk libc behind descriptors that are not ours */
void hle_clear_system_event(void *ev) { (void)ev; }
void hle_signal_system_event(void *ev) { (void)ev; }   /* account.c: the async contexts signal their event (threads.c in the runtime) */
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

int main(void) {
    if (!getenv("TOTK_PROFILE_DIR")) setenv("TOTK_PROFILE_DIR", "/tmp/fc26_fs9_test_profile", 1);

    /* Function pointers for existing and new fs overrides */
    unsigned char (*is_mounted)(const char *) =
        (unsigned char (*)(const char *))runtime_fs_host_override("_ZN2nn2fs9IsMountedEPKc");
    unsigned (*create_file)(const char *, int64_t) =
        (unsigned (*)(const char *, int64_t))runtime_fs_host_override("_ZN2nn2fs10CreateFileEPKcl");
    unsigned (*delete_file)(const char *) =
        (unsigned (*)(const char *))runtime_fs_host_override("_ZN2nn2fs10DeleteFileEPKc");
    unsigned (*open_file)(uint64_t *, const char *, int) =
        (unsigned (*)(uint64_t *, const char *, int))runtime_fs_host_override("_ZN2nn2fs8OpenFileEPNS0_10FileHandleEPKci");
    void (*close_file)(uint64_t) =
        (void (*)(uint64_t))runtime_fs_host_override("_ZN2nn2fs9CloseFileENS0_10FileHandleE");
    unsigned (*create_dir)(const char *) =
        (unsigned (*)(const char *))runtime_fs_host_override("_ZN2nn2fs15CreateDirectoryEPKc");
    unsigned (*open_dir)(uint64_t *, const char *, int) =
        (unsigned (*)(uint64_t *, const char *, int))runtime_fs_host_override("_ZN2nn2fs13OpenDirectoryEPNS0_15DirectoryHandleEPKci");
    void (*close_dir)(uint64_t) =
        (void (*)(uint64_t))runtime_fs_host_override("_ZN2nn2fs14CloseDirectoryENS0_15DirectoryHandleE");
    unsigned (*mount_temp)(const char *) =
        (unsigned (*)(const char *))runtime_fs_host_override("_ZN2nn2fs21MountTemporaryStorageEPKc");

    /* 9 new overrides */
    unsigned (*mount_cache_storage)(const char *) =
        (unsigned (*)(const char *))runtime_fs_host_override("_ZN2nn2fs17MountCacheStorageEPKc");
    unsigned (*get_cache_storage_max)(int *, int64_t *) =
        (unsigned (*)(int *, int64_t *))runtime_fs_host_override("_ZN2nn2fs18GetCacheStorageMaxEPiPl");
    unsigned (*get_cache_storage_size)(int64_t *, int64_t *, int) =
        (unsigned (*)(int64_t *, int64_t *, int))runtime_fs_host_override("_ZN2nn2fs19GetCacheStorageSizeEPlS1_i");
    unsigned (*get_free_space_size)(int64_t *, const char *) =
        (unsigned (*)(int64_t *, const char *))runtime_fs_host_override("_ZN2nn2fs16GetFreeSpaceSizeEPlPKc");
    unsigned (*delete_dir)(const char *) =
        (unsigned (*)(const char *))runtime_fs_host_override("_ZN2nn2fs15DeleteDirectoryEPKc");
    unsigned (*rename_dir)(const char *, const char *) =
        (unsigned (*)(const char *, const char *))runtime_fs_host_override("_ZN2nn2fs15RenameDirectoryEPKcS2_");
    unsigned (*get_entry_count)(int64_t *, uint64_t) =
        (unsigned (*)(int64_t *, uint64_t))runtime_fs_host_override("_ZN2nn2fs22GetDirectoryEntryCountEPlNS0_15DirectoryHandleE");
    unsigned (*mount_aoc)(const char *, int, void *, size_t) =
        (unsigned (*)(const char *, int, void *, size_t))runtime_fs_host_override("_ZN2nn2fs17MountAddOnContentEPKciPvm");
    unsigned (*query_aoc_cache_size)(size_t *, int) =
        (unsigned (*)(size_t *, int))runtime_fs_host_override("_ZN2nn2fs31QueryMountAddOnContentCacheSizeEPmi");

    assert(mount_cache_storage != NULL);
    assert(get_cache_storage_max != NULL);
    assert(get_cache_storage_size != NULL);
    assert(get_free_space_size != NULL);
    assert(delete_dir != NULL);
    assert(rename_dir != NULL);
    assert(get_entry_count != NULL);
    assert(mount_aoc != NULL);
    assert(query_aoc_cache_size != NULL);

    /* --- 1. MountCacheStorage(const char*) --- */
    assert(is_mounted("cst") == 0);
    assert(mount_cache_storage("cst") == 0);
    assert(is_mounted("cst") == 1);
    assert(mount_cache_storage("cst") == 0x7802u);   /* fs::ResultMountNameAlreadyExists */
    assert(mount_cache_storage(NULL) == R_INVALID_ARGUMENT);

    /* --- 2. GetCacheStorageMax(int*, long*) --- */
    int max_idx = -1;
    int64_t max_sz = -1;
    assert(get_cache_storage_max(&max_idx, &max_sz) == 0);
    assert(max_idx == 0);
    assert(max_sz == (1008730112LL + 33554432LL));
    assert(get_cache_storage_max(NULL, &max_sz) == R_INVALID_ARGUMENT);
    assert(get_cache_storage_max(&max_idx, NULL) == R_INVALID_ARGUMENT);

    /* --- 3. GetCacheStorageSize(long*, long*, int) --- */
    int64_t data_sz = -1, jour_sz = -1;
    assert(get_cache_storage_size(&data_sz, &jour_sz, 0) == 0);
    assert(data_sz == 1008730112LL);
    assert(jour_sz == 33554432LL);
    data_sz = -1; jour_sz = -1;
    assert(get_cache_storage_size(&data_sz, &jour_sz, 1) == R_TARGET_NOT_FOUND);
    assert(data_sz == 0 && jour_sz == 0);
    assert(get_cache_storage_size(&data_sz, &jour_sz, -1) == R_TARGET_NOT_FOUND);
    assert(data_sz == 0 && jour_sz == 0);
    assert(get_cache_storage_size(NULL, &jour_sz, 0) == R_INVALID_ARGUMENT);
    assert(get_cache_storage_size(&data_sz, NULL, 0) == R_INVALID_ARGUMENT);

    /* --- 4. GetFreeSpaceSize(long*, const char*) --- */
    int64_t free_sp = 0;
    assert(get_free_space_size(&free_sp, "cst:/") == 0);
    assert(free_sp > 0);
    int64_t free_sp2 = 0;
    assert(get_free_space_size(&free_sp2, "cst:") == 0);
    assert(free_sp2 > 0);
    int64_t free_sp3 = 0;
    assert(get_free_space_size(&free_sp3, "cst:/nonexistent_subpath") == 0);
    assert(free_sp3 > 0);
    assert(get_free_space_size(NULL, "cst:/") == R_INVALID_ARGUMENT);
    assert(get_free_space_size(&free_sp, NULL) == R_INVALID_PATH);
    assert(get_free_space_size(&free_sp, "unmounted:/") == R_PATH_NOT_FOUND);

    /* --- 5. CreateDirectory, GetDirectoryEntryCount, DeleteDirectory --- */
    assert(create_dir("cst:/testdir") == 0);
    uint64_t dh = 0;
    assert(open_dir(&dh, "cst:/testdir", 3) == 0);
    int64_t count = -1;
    assert(get_entry_count(&count, dh) == 0);
    assert(count == 0);
    close_dir(dh);

    /* Add a file inside testdir */
    assert(create_file("cst:/testdir/sample.bin", 16) == 0);
    assert(open_dir(&dh, "cst:/testdir", 3) == 0);
    count = -1;
    assert(get_entry_count(&count, dh) == 0);
    assert(count == 1);
    close_dir(dh);

    /* Mode filter: directories only (mode 1) should return 0 */
    assert(open_dir(&dh, "cst:/testdir", 1) == 0);
    count = -1;
    assert(get_entry_count(&count, dh) == 0);
    assert(count == 0);
    close_dir(dh);

    /* DeleteDirectory must fail when directory is not empty */
    assert(delete_dir("cst:/testdir") == R_NOT_EMPTY);

    /* Delete file, then DeleteDirectory must succeed */
    assert(delete_file("cst:/testdir/sample.bin") == 0);
    assert(delete_dir("cst:/testdir") == 0);

    /* Deleting non-existent directory returns R_PATH_NOT_FOUND */
    assert(delete_dir("cst:/testdir") == R_PATH_NOT_FOUND);

    /* Deleting root returns R_INVALID_PATH */
    assert(delete_dir("cst:/") == R_INVALID_PATH);

    /* Invalid handle for GetDirectoryEntryCount */
    assert(get_entry_count(&count, 0x12345) == R_INVALID_ARGUMENT);
    assert(get_entry_count(NULL, dh) == R_INVALID_ARGUMENT);

    /* --- 6. RenameDirectory --- */
    assert(mount_temp("tmp") == 0);
    assert(create_dir("cst:/orig_dir") == 0);
    assert(create_file("cst:/orig_dir/inner.txt", 8) == 0);

    /* Rename within same mount */
    assert(rename_dir("cst:/orig_dir", "cst:/moved_dir") == 0);
    uint64_t fh = 0;
    assert(open_file(&fh, "cst:/moved_dir/inner.txt", 1) == 0);
    close_file(fh);

    /* Rename across different mounts must be rejected */
    assert(rename_dir("cst:/moved_dir", "tmp:/moved_dir") == R_INVALID_ARGUMENT);

    /* Rename to already existing directory must fail */
    assert(create_dir("cst:/existing") == 0);
    assert(rename_dir("cst:/moved_dir", "cst:/existing") == R_ALREADY_EXISTS);

    /* Clean up */
    assert(delete_file("cst:/moved_dir/inner.txt") == 0);
    assert(delete_dir("cst:/moved_dir") == 0);
    assert(delete_dir("cst:/existing") == 0);

    /* --- 7. MountAddOnContent & QueryMountAddOnContentCacheSize --- */
    assert(mount_aoc("aoc0", 0, NULL, 0) == R_TARGET_NOT_FOUND);
    assert(mount_aoc("aoc1", 1, NULL, 0) == R_TARGET_NOT_FOUND);
    assert(mount_aoc(NULL, 0, NULL, 0) == R_INVALID_ARGUMENT);

    size_t aoc_cache_sz = 999;
    assert(query_aoc_cache_size(&aoc_cache_sz, 0) == R_TARGET_NOT_FOUND);
    assert(aoc_cache_sz == 0);
    assert(query_aoc_cache_size(NULL, 0) == R_INVALID_ARGUMENT);

    printf("ALL_FS_OVERRIDES_OK\n");
    return 0;
}
