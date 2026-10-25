/* Synthetic test harness for nn::hid overrides in FC 26 runtime:
   Npad styles, Keyboard mapping, ControllerSupport, and safe vibration no-op overrides. */
#include "runtime.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <stdbool.h>

/* Minimal stubs required to link input.c and hid_feedback.c standalone */
static uint64_t fake_now = 1000000000ULL;
uint64_t runtime_now_ns(void) { return (fake_now += 1000000); }
void runtime_survey_cancel_user(void) {}
void runtime_autoload_user_input(void) {}
void runtime_shortcut_help_toggle(void) {}
void dm_gfx_set_flag(const char *name, int v) { (void)name; (void)v; }
int runtime_output_mode_cycle(void) { return 0; }
int runtime_aspect_toggle(void) { return 0; }
void runtime_input_key_synthetic(unsigned code, int down);

static int s_handheld = 0;
int runtime_handheld_mode(void) { return s_handheld; }

static RuntimeGamepadState s_pad = {0};
void runtime_gamepad_read(RuntimeGamepadState *out) { *out = s_pad; }
void runtime_gamepad_clear(void) { memset(&s_pad, 0, sizeof(s_pad)); }

static int s_rumble_calls = 0;
void runtime_rumble_set(unsigned side, float al, float fl, float ah, float fh) {
    (void)side; (void)al; (void)fl; (void)ah; (void)fh;
    s_rumble_calls++;
}

int runtime_motion_read(RuntimeMotionState *m, int max) { (void)m; (void)max; return 0; }
void runtime_motion_start(void) {}
void dm_gfx_shot_at(long f, const char *p) { (void)f; (void)p; }
void runtime_front_request_close(void) {}
void dm_gfx_passdump_next(long n) { (void)n; }
void dm_gfx_gpucapture_next(const char *p) { (void)p; }
void dm_gfx_anomdump(void) {}
void dm_gfx_querylog_next(long n) { (void)n; }
void dm_gfx_texdump_next(const char *p) { (void)p; }
void dm_gfx_window_shot(const char *p) { (void)p; }
void runtime_swkbd_selftest(void) {}
void runtime_front_text_test(const char *o, const char *t) { (void)o; (void)t; }
void runtime_hle_trace_set(int m) { (void)m; }
void runtime_frame_step_pin(double m) { (void)m; }
int runtime_timer_diagnostic_limit(uint64_t ns) {(void)ns;return 0;}
void runtime_dump_threads(void) {}
int runtime_survey_command(const char *l) { (void)l; return 0; }

_Noreturn void runtime_fail(const char *s) {
    fprintf(stderr, "FATAL: %s\n", s);
    exit(1);
}

typedef struct {
    int64_t sampling;
    uint64_t buttons;
    int32_t lx, ly, rx, ry;
    uint32_t attributes, pad;
} TestNpadState;

typedef struct {
    int8_t players;
    uint8_t pad[3];
    uint32_t selected;
} TestControllerSupportResult;

typedef struct {
    float amp_low, freq_low, amp_high, freq_high;
} TestVibrationValue;

typedef struct {
    uint32_t type, position;
} TestVibrationDeviceInfo;

int main(void) {
    printf("[test_input] starting input and hid override checks...\n");

    /* 1. Check override presence for required vibration functions */
    void *vib_init_fn = runtime_input_override("_ZN2nn3hid25InitializeVibrationDeviceERKNS0_21VibrationDeviceHandleE");
    if (!vib_init_fn) {
        fprintf(stderr, "FAIL: _ZN2nn3hid25InitializeVibrationDeviceERKNS0_21VibrationDeviceHandleE not found in runtime_input_override\n");
        return 1;
    }

    /* VibrationNode::Update: host no-op without rumble; with TOTK_RUMBLE=1 the sdk's own mixes into detail::SendVibrationValues */
    void *vib_update_fn = runtime_input_override("_ZN2nn3hid13VibrationNode6UpdateEv");
    int rumble_on = getenv("TOTK_RUMBLE") && !strcmp(getenv("TOTK_RUMBLE"), "1");
    if (rumble_on ? vib_update_fn != NULL : vib_update_fn == NULL) {
        fprintf(stderr, "FAIL: _ZN2nn3hid13VibrationNode6UpdateEv override must exist only without rumble\n");
        return 1;
    }

    /* 2. Initialize Npad */
    void (*npad_init)(void) = (void (*)(void))runtime_input_override("_ZN2nn3hid14InitializeNpadEv");
    assert(npad_init != NULL);
    npad_init();

    /* 3. Supported Npad IDs */
    void (*set_ids)(const uint32_t *, uint64_t) = (void (*)(const uint32_t *, uint64_t))runtime_input_override("_ZN2nn3hid22SetSupportedNpadIdTypeEPKjm");
    assert(set_ids != NULL);
    uint32_t fc26_ids[9] = {0, 1, 2, 3, 4, 5, 6, 7, 0x20};
    set_ids(fc26_ids, 9);

    /* 4. Supported Styles */
    void (*set_styles)(uint32_t) = (void (*)(uint32_t))runtime_input_override("_ZN2nn3hid24SetSupportedNpadStyleSetENS_4util10BitFlagSetILi32ENS0_12NpadStyleTagEEE");
    uint32_t (*get_styles)(void) = (uint32_t (*)(void))runtime_input_override("_ZN2nn3hid24GetSupportedNpadStyleSetEv");
    uint32_t (*get_style_set)(const uint32_t *) = (uint32_t (*)(const uint32_t *))runtime_input_override("_ZN2nn3hid15GetNpadStyleSetERKj");
    assert(set_styles && get_styles && get_style_set);

    /* FC 26 passes 0x7 and 0x1f */
    set_styles(0x7);
    assert(get_styles() == 0x7);

    uint32_t id_p1 = 0;
    uint32_t id_p2 = 1;
    uint32_t id_handheld = 0x20;

    /* In docked mode: player 1 is FullKey (bit 0 = 1) */
    s_handheld = 0;
    set_ids(fc26_ids, 9);
    assert(get_style_set(&id_p1) == 1);
    assert(get_style_set(&id_p2) == 0); /* player 2 not connected */

    /* Set 0x1f */
    set_styles(0x1f);
    assert(get_styles() == 0x1f);
    assert(get_style_set(&id_p1) == 1);

    /* In handheld mode: player 1 not connected, handheld controller has bit 1 (2) */
    s_handheld = 1;
    set_ids(fc26_ids, 9);
    assert(get_style_set(&id_p1) == 0);
    assert(get_style_set(&id_handheld) == 2);

    /* Switch back to docked */
    s_handheld = 0;
    set_ids(fc26_ids, 9);

    /* 5. Controller Support Applet */
    uint32_t (*show_cs_arg)(const void *) = (uint32_t (*)(const void *))runtime_input_override("_ZN2nn3hid21ShowControllerSupportERKNS0_20ControllerSupportArgE");
    uint32_t (*show_cs)(TestControllerSupportResult *, const void *) = (uint32_t (*)(TestControllerSupportResult *, const void *))runtime_input_override("_ZN2nn3hid21ShowControllerSupportEPNS0_27ControllerSupportResultInfoERKNS0_20ControllerSupportArgE");
    assert(show_cs_arg && show_cs);

    uint32_t res_arg = show_cs_arg(NULL);
    assert(res_arg == 0);

    TestControllerSupportResult cs_result;
    memset(&cs_result, 0x55, sizeof(cs_result));
    uint32_t res_info = show_cs(&cs_result, NULL);
    assert(res_info == 0);
    assert(cs_result.players == 1);
    assert(cs_result.selected == 0); /* player 1 */

    /* 6. Keyboard mapping to Npad full-key state */
    int (*get_full_states)(TestNpadState *, int, const uint32_t *) = (int (*)(TestNpadState *, int, const uint32_t *))runtime_input_override("_ZN2nn3hid13GetNpadStatesEPNS0_16NpadFullKeyStateEiRKj");
    assert(get_full_states != NULL);

    runtime_input_clear();
    TestNpadState state;
    int read_count = get_full_states(&state, 1, &id_p1);
    assert(read_count == 1);
    assert(state.attributes == 1); /* connected */
    assert(state.buttons == 0);
    assert(state.lx == 0 && state.ly == 0 && state.rx == 0 && state.ry == 0);

    /* Test buttons: J = 38 (A), K = 40 (B), I = 34 (X), U = 32 (Y) */
    runtime_input_key_synthetic(38, 1);
    get_full_states(&state, 1, &id_p1);
    assert((state.buttons & 1) != 0); /* A */
    runtime_input_key_synthetic(38, 0);

    runtime_input_key_synthetic(40, 1);
    get_full_states(&state, 1, &id_p1);
    assert((state.buttons & 2) != 0); /* B */
    runtime_input_key_synthetic(40, 0);

    runtime_input_key_synthetic(34, 1);
    get_full_states(&state, 1, &id_p1);
    assert((state.buttons & 4) != 0); /* X */
    runtime_input_key_synthetic(34, 0);

    runtime_input_key_synthetic(32, 1);
    get_full_states(&state, 1, &id_p1);
    assert((state.buttons & 8) != 0); /* Y */
    runtime_input_key_synthetic(32, 0);

    /* Test Left stick: A = 0 (Left), D = 2 (Right), S = 1 (Down), W = 13 (Up) */
    runtime_input_key_synthetic(0, 1);
    get_full_states(&state, 1, &id_p1);
    assert(state.lx == -32767);
    runtime_input_key_synthetic(0, 0);

    runtime_input_key_synthetic(2, 1);
    get_full_states(&state, 1, &id_p1);
    assert(state.lx == 32767);
    runtime_input_key_synthetic(2, 0);

    runtime_input_key_synthetic(1, 1);
    get_full_states(&state, 1, &id_p1);
    assert(state.ly == -32767);
    runtime_input_key_synthetic(1, 0);

    runtime_input_key_synthetic(13, 1);
    get_full_states(&state, 1, &id_p1);
    assert(state.ly == 32767);
    runtime_input_key_synthetic(13, 0);

    /* Test Right stick: 123 (Left), 124 (Right), 125 (Down), 126 (Up) */
    runtime_input_key_synthetic(123, 1);
    get_full_states(&state, 1, &id_p1);
    assert(state.rx == -32767);
    runtime_input_key_synthetic(123, 0);

    runtime_input_key_synthetic(124, 1);
    get_full_states(&state, 1, &id_p1);
    assert(state.rx == 32767);
    runtime_input_key_synthetic(124, 0);

    runtime_input_key_synthetic(125, 1);
    get_full_states(&state, 1, &id_p1);
    assert(state.ry == -32767);
    runtime_input_key_synthetic(125, 0);

    runtime_input_key_synthetic(126, 1);
    get_full_states(&state, 1, &id_p1);
    assert(state.ry == 32767);
    runtime_input_key_synthetic(126, 0);

    /* Test D-Pad: F = 3 (Left), T = 17 (Up), H = 4 (Right), G = 5 (Down) */
    runtime_input_key_synthetic(3, 1);
    get_full_states(&state, 1, &id_p1);
    assert((state.buttons & 4096) != 0);
    runtime_input_key_synthetic(3, 0);

    runtime_input_key_synthetic(17, 1);
    get_full_states(&state, 1, &id_p1);
    assert((state.buttons & 8192) != 0);
    runtime_input_key_synthetic(17, 0);

    runtime_input_key_synthetic(4, 1);
    get_full_states(&state, 1, &id_p1);
    assert((state.buttons & 16384) != 0);
    runtime_input_key_synthetic(4, 0);

    runtime_input_key_synthetic(5, 1);
    get_full_states(&state, 1, &id_p1);
    assert((state.buttons & 32768) != 0);
    runtime_input_key_synthetic(5, 0);

    /* 7. Vibration device handling (no vibration device / safe no-op) */
    /* When rumble is off, GetVibrationDeviceHandles reports 0 handles */
    int (*get_vib_handles)(uint32_t *, int, const uint32_t *, uint32_t) =
        (int (*)(uint32_t *, int, const uint32_t *, uint32_t))runtime_input_override("_ZN2nn3hid25GetVibrationDeviceHandlesEPNS0_21VibrationDeviceHandleEiRKjNS_4util10BitFlagSetILi32ENS0_12NpadStyleTagEEE");
    if (get_vib_handles) {
        uint32_t handles[2] = {0xdead, 0xbeef};
        int num_handles = get_vib_handles(handles, 2, &id_p1, 1);
        assert(num_handles == 0); /* reports 0: device without vibration */
    }

    /* InitializeVibrationDevice must return 0 safely for handles */
    uint32_t (*init_vib)(const uint32_t *) = (uint32_t (*)(const uint32_t *))vib_init_fn;
    uint32_t sample_handle = 0x00000003; /* style 3 (full key), id 0, dev 0 */
    assert(init_vib(&sample_handle) == 0);

    /* VibrationNode::Update must execute cleanly without calling AbortImpl */
    if (vib_update_fn) { void (*update_vib)(void) = (void (*)(void))vib_update_fn; update_vib(); }

    /* detail::IsVibrationPermitted must report true */
    uint32_t (*vib_perm)(bool *) = (uint32_t (*)(bool *))runtime_input_override("_ZN2nn3hid6detail20IsVibrationPermittedEPb");
    assert(vib_perm != NULL);
    bool permitted = false;
    assert(vib_perm(&permitted) == 0 && permitted == true);

    /* detail::GetVibrationDeviceInfo */
    uint32_t (*vib_info)(TestVibrationDeviceInfo *, const uint32_t *) =
        (uint32_t (*)(TestVibrationDeviceInfo *, const uint32_t *))runtime_input_override("_ZN2nn3hid6detail22GetVibrationDeviceInfoEPNS0_19VibrationDeviceInfoERKNS0_21VibrationDeviceHandleE");
    assert(vib_info != NULL);
    TestVibrationDeviceInfo vinfo;
    assert(vib_info(&vinfo, &sample_handle) == 0);
    assert(vinfo.type == 1);

    printf("ALL_INPUT_OVERRIDES_OK\n");
    return 0;
}
