/* Behavioral round-trip test for save data in FC 26:
   Simulates full save lifecycle across game boots:
   Cycle 1: MountSaveData, CreateDirectory, CreateFile, OpenFile, WriteFile, CloseFile, CommitSaveData, Unmount.
   Cycle 2: In a fresh process invocation with same TOTK_PROFILE_DIR, verify account UID persistence,
            MountSaveData, OpenFile, ReadFile, byte-for-byte validation, ExtendSaveData, GetFreeSpaceSize, Unmount.
   Also validates SDK variants and mount name normalization ("save" vs "save:"). */
#include "runtime.h"
#include "fs_host.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <stdbool.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>

#define R_PATH_NOT_FOUND 0x202u
#define R_ALREADY_EXISTS 0x402u
#define R_TARGET_NOT_FOUND 0x7d402u
#define R_INVALID_ARGUMENT 0x2ee202u
#define R_INVALID_PATH 0x2ee602u

pthread_key_t runtime_keys[8];
void *runtime_symbol(const char *name) { (void)name; return NULL; }
void hle_clear_system_event(void *ev) { (void)ev; }
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

#define TEST_PAYLOAD_SIZE 2048

static void generate_test_payload(uint8_t *buf, size_t len, uint8_t seed) {
    for (size_t i = 0; i < len; i++) {
        buf[i] = (uint8_t)((i * 37 + seed) & 0xff);
    }
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <phase: 1=write, 2=read_verify>\n", argv[0]);
        return 1;
    }
    int phase = atoi(argv[1]);

    /* Function pointers from runtime_fs_host_override */
    unsigned (*mount_save)(const char *, const uint64_t *) =
        (unsigned (*)(const char *, const uint64_t *))runtime_fs_host_override("_ZN2nn2fs13MountSaveDataEPKcRKNS_7account3UidE");
    unsigned char (*is_mounted)(const char *) =
        (unsigned char (*)(const char *))runtime_fs_host_override("_ZN2nn2fs9IsMountedEPKc");
    unsigned (*create_file)(const char *, int64_t) =
        (unsigned (*)(const char *, int64_t))runtime_fs_host_override("_ZN2nn2fs10CreateFileEPKcl");
    unsigned (*create_dir)(const char *) =
        (unsigned (*)(const char *))runtime_fs_host_override("_ZN2nn2fs15CreateDirectoryEPKc");
    unsigned (*open_file)(uint64_t *, const char *, int) =
        (unsigned (*)(uint64_t *, const char *, int))runtime_fs_host_override("_ZN2nn2fs8OpenFileEPNS0_10FileHandleEPKci");
    unsigned (*write_file)(uint64_t, int64_t, const void *, size_t, const int *) =
        (unsigned (*)(uint64_t, int64_t, const void *, size_t, const int *))runtime_fs_host_override("_ZN2nn2fs9WriteFileENS0_10FileHandleElPKvmRKNS0_11WriteOptionE");
    unsigned (*read_file)(uint64_t *, uint64_t, int64_t, void *, size_t) =
        (unsigned (*)(uint64_t *, uint64_t, int64_t, void *, size_t))runtime_fs_host_override("_ZN2nn2fs8ReadFileEPmNS0_10FileHandleElPvm");
    void (*close_file)(uint64_t) =
        (void (*)(uint64_t))runtime_fs_host_override("_ZN2nn2fs9CloseFileENS0_10FileHandleE");
    unsigned (*commit_save_data)(const char *) =
        (unsigned (*)(const char *))runtime_fs_host_override("_ZN2nn2fs14CommitSaveDataEPKc");
    unsigned (*commit_fs)(const char *) =
        (unsigned (*)(const char *))runtime_fs_host_override("_ZN2nn2fs6CommitEPKc");
    void (*unmount)(const char *) =
        (void (*)(const char *))runtime_fs_host_override("_ZN2nn2fs7UnmountEPKc");
    unsigned (*get_save_data_size)(int64_t *, int64_t *, const uint64_t *) =
        (unsigned (*)(int64_t *, int64_t *, const uint64_t *))runtime_fs_host_override("_ZN2nn2fs15GetSaveDataSizeEPlS1_RKNS_7account3UidE");
    unsigned (*get_save_data_size_max)(int64_t *, int64_t *) =
        (unsigned (*)(int64_t *, int64_t *))runtime_fs_host_override("_ZN2nn2fs18GetSaveDataSizeMaxEPlS1_");
    unsigned (*extend_save_data)(const uint64_t *, int64_t, int64_t) =
        (unsigned (*)(const uint64_t *, int64_t, int64_t))runtime_fs_host_override("_ZN2nn2fs14ExtendSaveDataERKNS_7account3UidEll");
    unsigned (*get_free_space_size)(int64_t *, const char *) =
        (unsigned (*)(int64_t *, const char *))runtime_fs_host_override("_ZN2nn2fs16GetFreeSpaceSizeEPlPKc");
    unsigned char (*save_exists)(uint64_t, const uint64_t *) =
        (unsigned char (*)(uint64_t, const uint64_t *))runtime_fs_host_override("_ZN2nn2fs18IsSaveDataExistingENS_13ApplicationIdERKNS_7account3UidE");

    assert(mount_save != NULL);
    assert(is_mounted != NULL);
    assert(create_file != NULL);
    assert(create_dir != NULL);
    assert(open_file != NULL);
    assert(write_file != NULL);
    assert(read_file != NULL);
    assert(close_file != NULL);
    assert(commit_save_data != NULL);
    assert(commit_fs != NULL);
    assert(unmount != NULL);
    assert(get_save_data_size != NULL);
    assert(get_save_data_size_max != NULL);
    assert(extend_save_data != NULL);
    assert(get_free_space_size != NULL);
    assert(save_exists != NULL);

    /* Verify extra SDK variants of IsSaveDataExisting */
    unsigned char (*save_exists_uid_only)(const uint64_t *) =
        (unsigned char (*)(const uint64_t *))runtime_fs_host_override("_ZN2nn2fs18IsSaveDataExistingERKNS_7account3UidE");
    unsigned (*save_exists_ptr)(bool *, uint64_t, const uint64_t *) =
        (unsigned (*)(bool *, uint64_t, const uint64_t *))runtime_fs_host_override("_ZN2nn2fs18IsSaveDataExistingEPbNS_13ApplicationIdERKNS_7account3UidE");
    unsigned (*save_exists_ptr_uid)(bool *, const uint64_t *) =
        (unsigned (*)(bool *, const uint64_t *))runtime_fs_host_override("_ZN2nn2fs18IsSaveDataExistingEPbRKNS_7account3UidE");

    if (!save_exists_uid_only || !save_exists_ptr || !save_exists_ptr_uid) {
        fprintf(stderr, "FAIL: IsSaveDataExisting variants missing in runtime_fs_host_override\n");
        return 2;
    }

    uint64_t uid[2];
    runtime_account_uid(uid);
    assert(uid[0] != 0 || uid[1] != 0);

    /* Verify IsSaveDataExisting */
    assert(save_exists(0x01004ff021942000ULL, uid) == 1);
    assert(save_exists_uid_only(uid) == 1);
    bool exists_out = false;
    assert(save_exists_ptr(&exists_out, 0x01004ff021942000ULL, uid) == 0 && exists_out == true);
    exists_out = false;
    assert(save_exists_ptr_uid(&exists_out, uid) == 0 && exists_out == true);

    uint64_t dummy_uid[2] = {uid[0] ^ 0x1234, uid[1] ^ 0x5678};
    assert(save_exists(0x01004ff021942000ULL, dummy_uid) == 0);
    assert(save_exists_uid_only(dummy_uid) == 0);

    if (phase == 1) {
        /* Phase 1: Mount, create dir, create file, write, commit, unmount */
        assert(is_mounted("save") == 0);
        unsigned res = mount_save("save", uid);
        assert(res == 0);
        assert(is_mounted("save") == 1);

        /* Query initial save sizes matching NACP (62 MiB init data, 16 MiB init journal) */
        int64_t cur_d = 0, cur_j = 0;
        assert(get_save_data_size(&cur_d, &cur_j, uid) == 0);
        assert(cur_d == 65011712LL);
        assert(cur_j == 16777216LL);

        /* Query max save sizes matching NACP (962 MiB max data, 32 MiB max journal) */
        int64_t max_d = 0, max_j = 0;
        assert(get_save_data_size_max(&max_d, &max_j) == 0);
        assert(max_d == 1008730112LL);
        assert(max_j == 33554432LL);

        /* Create directory inside save */
        res = create_dir("save:/career");
        assert(res == 0 || res == R_ALREADY_EXISTS);

        /* Create save file */
        res = create_file("save:/career/slot1.sav", TEST_PAYLOAD_SIZE);
        assert(res == 0 || res == R_ALREADY_EXISTS);

        /* Open for writing */
        uint64_t fh = 0;
        res = open_file(&fh, "save:/career/slot1.sav", 2 /* OPEN_WRITE */);
        assert(res == 0);
        assert(fh != 0);

        /* Generate payload and write */
        uint8_t payload[TEST_PAYLOAD_SIZE];
        generate_test_payload(payload, sizeof(payload), 0x5a);
        int opt = 0;
        res = write_file(fh, 0, payload, sizeof(payload), &opt);
        assert(res == 0);

        close_file(fh);

        /* CommitSaveData test with clean name and colon normalization */
        res = commit_save_data("save");
        assert(res == 0);

        res = commit_fs("save:");
        assert(res == 0);

        /* Unmount with colon normalization */
        unmount("save:");
        assert(is_mounted("save") == 0);

        printf("PHASE_1_WRITE_OK\n");
        return 0;
    } else if (phase == 2) {
        /* Phase 2: Fresh boot, mount save, verify payload, extend save, free space, unmount */
        assert(is_mounted("save") == 0);
        unsigned res = mount_save("save", uid);
        assert(res == 0);
        assert(is_mounted("save") == 1);

        uint64_t fh = 0;
        res = open_file(&fh, "save:/career/slot1.sav", 1 /* OPEN_READ */);
        assert(res == 0);
        assert(fh != 0);

        uint8_t readbuf[TEST_PAYLOAD_SIZE];
        memset(readbuf, 0, sizeof(readbuf));
        uint64_t bytes_read = 0;
        res = read_file(&bytes_read, fh, 0, readbuf, sizeof(readbuf));
        assert(res == 0);
        assert(bytes_read == TEST_PAYLOAD_SIZE);

        uint8_t expected[TEST_PAYLOAD_SIZE];
        generate_test_payload(expected, sizeof(expected), 0x5a);
        assert(memcmp(readbuf, expected, TEST_PAYLOAD_SIZE) == 0);

        close_file(fh);

        /* Test ExtendSaveData (extend within NACP max: 100 MiB data, 20 MiB journal) */
        int64_t new_data = 104857600LL;
        int64_t new_journal = 20971520LL;
        assert(extend_save_data(uid, new_data, new_journal) == 0);

        int64_t cur_d = 0, cur_j = 0;
        assert(get_save_data_size(&cur_d, &cur_j, uid) == 0);
        assert(cur_d == new_data);
        assert(cur_j == new_journal);

        /* Test extending beyond NACP max must fail with R_INVALID_ARGUMENT */
        assert(extend_save_data(uid, 2000000000LL, new_journal) == R_INVALID_ARGUMENT);
        assert(extend_save_data(uid, new_data, 100000000LL) == R_INVALID_ARGUMENT);

        /* Test GetFreeSpaceSize on save mount */
        int64_t free_bytes = 0;
        assert(get_free_space_size(&free_bytes, "save:/") == 0);
        assert(free_bytes > 0);

        free_bytes = 0;
        assert(get_free_space_size(&free_bytes, "save:") == 0);
        assert(free_bytes > 0);

        unmount("save");
        assert(is_mounted("save") == 0);

        printf("PHASE_2_READ_VERIFY_OK\n");
        return 0;
    }

    fprintf(stderr, "Unknown phase: %d\n", phase);
    return 1;
}
