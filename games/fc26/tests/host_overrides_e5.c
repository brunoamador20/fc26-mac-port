/* Behavioral tests for FC 26 Story 5 host overrides:
   OpenUser, ShowUserSelector, GetSupportedNpadStyleSet, InitializeGesture,
   GetGestureStates, IsMounted, GetSaveDataSize, GetSaveDataSizeMax, ExtendSaveData,
   ListAudioIns and audin:u. */
#include "runtime.h"
#include "fs_host.h"
#include "ipc.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <stdbool.h>

typedef struct { uint64_t lo, hi; } Uid;
typedef struct { Uid uid; uint64_t token; } UserHandle;

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

void dm_gfx_anomdump(void) {}
void dm_gfx_gpucapture_next(void) {}
void dm_gfx_passdump_next(void) {}
void dm_gfx_querylog_next(void) {}
void dm_gfx_set_flag(int flag, int value) { (void)flag; (void)value; }
void dm_gfx_shot_at(uint64_t frame, const char *name) { (void)frame; (void)name; }
void dm_gfx_texdump_next(void) {}
void dm_gfx_window_shot(const char *name) { (void)name; }
int runtime_aspect_toggle(void) { return 0; }
void runtime_dump_threads(void) {}
void runtime_frame_step_pin(double ms) { (void)ms; }
void runtime_front_request_close(void) {}
void runtime_front_text_test(const char *op, const char *text) { (void)op; (void)text; }
void runtime_gamepad_clear(void) {}
void runtime_gamepad_read(RuntimeGamepadState *out) { (void)out; }
int runtime_hid_feedback_flag(const char *name, int v) { (void)name; (void)v; return 0; }
void runtime_hle_trace_set(int mode) { (void)mode; }
int runtime_output_mode_cycle(void) { return 0; }
void runtime_shortcut_help_toggle(void) {}
void runtime_survey_cancel_user(void) {}
void runtime_survey_command(const char *cmd) { (void)cmd; }
void runtime_swkbd_selftest(void) {}

int main(void) {
    if (!getenv("TOTK_PROFILE_DIR")) setenv("TOTK_PROFILE_DIR", "/tmp/fc26_overrides_test_profile", 1);
    /* 1. nn::account::OpenUser */
    uint32_t (*open_user)(UserHandle *, const Uid *) = (uint32_t (*)(UserHandle *, const Uid *))runtime_account_override("_ZN2nn7account8OpenUserEPNS0_10UserHandleERKNS0_3UidE");
    assert(open_user != NULL);
    uint64_t me[2];
    runtime_account_uid(me);
    Uid local_uid = {me[0], me[1]};
    UserHandle h = {{0, 0}, 0};
    assert(open_user(&h, &local_uid) == 0);
    assert(h.uid.lo == local_uid.lo && h.uid.hi == local_uid.hi);
    assert(h.token != 0);
    Uid wrong = {local_uid.lo ^ 0xdead, local_uid.hi ^ 0xbeef};
    assert(open_user(&h, &wrong) != 0);

    /* 2. nn::account::ShowUserSelector */
    uint32_t (*show_selector)(Uid *, const void *) = (uint32_t (*)(Uid *, const void *))runtime_account_override("_ZN2nn7account16ShowUserSelectorEPNS0_3UidERKNS0_21UserSelectionSettingsE");
    assert(show_selector != NULL);
    Uid sel = {0, 0};
    assert(show_selector(&sel, NULL) == 0);
    assert(sel.lo == local_uid.lo && sel.hi == local_uid.hi);

    /* 3. nn::hid::GetSupportedNpadStyleSet */
    uint32_t (*get_styles)(void) = (uint32_t (*)(void))runtime_input_override("_ZN2nn3hid24GetSupportedNpadStyleSetEv");
    assert(get_styles != NULL);
    void (*set_styles)(uint32_t) = (void (*)(uint32_t))runtime_input_override("_ZN2nn3hid24SetSupportedNpadStyleSetENS_4util10BitFlagSetILi32ENS0_12NpadStyleTagEEE");
    assert(set_styles != NULL);
    set_styles(0x1f);
    assert(get_styles() == 0x1f);
    set_styles(0x07);
    assert(get_styles() == 0x07);

    /* 4. nn::hid::InitializeGesture and GetGestureStates */
    void (*init_gesture)(void) = (void (*)(void))runtime_input_override("_ZN2nn3hid17InitializeGestureEv");
    assert(init_gesture != NULL);
    init_gesture();
    int (*get_gestures)(void *, int) = (int (*)(void *, int))runtime_input_override("_ZN2nn3hid16GetGestureStatesEPNS0_12GestureStateEi");
    assert(get_gestures != NULL);
    uint8_t gbuf[0x38 * 4];
    memset(gbuf, 0xaa, sizeof gbuf);
    int ng = get_gestures(gbuf, 4);
    assert(ng == 0);
    /* GestureState size is not proven: get_gesture_states must not write to the buffer */
    for (size_t i = 0; i < sizeof gbuf; i++) {
        assert(gbuf[i] == 0xaa);
    }

    /* 5. nn::fs::IsMounted */
    unsigned char (*is_mounted)(const char *) = (unsigned char (*)(const char *))runtime_fs_host_override("_ZN2nn2fs9IsMountedEPKc");
    assert(is_mounted != NULL);
    assert(is_mounted("save") == 0);
    assert(is_mounted("rom") == 1);
    unsigned (*mount_temp)(const char *) = (unsigned (*)(const char *))runtime_fs_host_override("_ZN2nn2fs21MountTemporaryStorageEPKc");
    assert(mount_temp != NULL);
    assert(mount_temp("tmp") == 0);
    assert(is_mounted("tmp") == 1);

    /* 6. nn::fs save data sizes: GetSaveDataSizeMax, GetSaveDataSize, ExtendSaveData */
    unsigned (*get_save_max)(int64_t *, int64_t *) = (unsigned (*)(int64_t *, int64_t *))runtime_fs_host_override("_ZN2nn2fs18GetSaveDataSizeMaxEPlS1_");
    assert(get_save_max != NULL);
    int64_t max_d = 0, max_j = 0;
    assert(get_save_max(&max_d, &max_j) == 0);
    assert(max_d == 1008730112LL);
    assert(max_j == 33554432LL);

    unsigned (*get_save_size)(int64_t *, int64_t *, const uint64_t *) = (unsigned (*)(int64_t *, int64_t *, const uint64_t *))runtime_fs_host_override("_ZN2nn2fs15GetSaveDataSizeEPlS1_RKNS_7account3UidE");
    assert(get_save_size != NULL);
    int64_t cur_d = 0, cur_j = 0;
    assert(get_save_size(&cur_d, &cur_j, me) == 0);
    assert(cur_d == 65011712LL);
    assert(cur_j == 16777216LL);
    uint64_t bad_uid[2] = {me[0] ^ 1, me[1]};
    assert(get_save_size(&cur_d, &cur_j, bad_uid) != 0);

    unsigned (*extend_save)(const uint64_t *, int64_t, int64_t) = (unsigned (*)(const uint64_t *, int64_t, int64_t))runtime_fs_host_override("_ZN2nn2fs14ExtendSaveDataERKNS_7account3UidEll");
    assert(extend_save != NULL);
    assert(extend_save(bad_uid, 70000000LL, 20000000LL) != 0);
    assert(extend_save(me, 70000000LL, 20000000LL) == 0);
    assert(get_save_size(&cur_d, &cur_j, me) == 0);
    assert(cur_d == 70000000LL);
    assert(cur_j == 20000000LL);

    /* 7. nn::audio::ListAudioIns */
    int (*list_audio_ins)(void *, int) = (int (*)(void *, int))runtime_game_override("_ZN2nn5audio12ListAudioInsEPNS0_11AudioInInfoEi");
    assert(list_audio_ins != NULL);
    assert(list_audio_ins(NULL, 10) == 0);

    /* AcquireAudioDeviceNotificationForInput must not be overridden on host (SDK handles it via audin:u IPC) */
    assert(runtime_game_override("_ZN2nn5audio38AcquireAudioDeviceNotificationForInputEPNS_2os11SystemEventE") == NULL);

    printf("ALL_OVERRIDES_OK\n");
    return 0;
}
