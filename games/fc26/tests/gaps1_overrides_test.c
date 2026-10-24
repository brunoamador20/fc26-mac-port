/* Synthetic test harness for gaps 1 overrides in FC 26 runtime:
   nn::vi:
     - GetLatestFrameNumber
     - ListFrameHistory
   nn::nifm:
     - SubmitNetworkRequest
     - IsNetworkRequestOnHold
     - GetCurrentPrimaryIpAddress (in_addr)
   nn::err:
     - ShowError (ErrorCode)
*/
#include "runtime.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <netinet/in.h>

/* Minimal stubs required to link frontend.m & system_services.c & applet_host.c */
void hle_bind_system_event(void *ev, int autoclear) { (void)ev; (void)autoclear; }
void hle_clear_system_event(void *ev) { (void)ev; }
void hle_signal_system_event(void *ev) { (void)ev; }
int runtime_fs_save_busy(void) { return 0; }
void runtime_gamepad_start(void) {}
void runtime_input_clear(void) {}
void runtime_input_key(unsigned code, int down) { (void)code; (void)down; }
uint64_t runtime_now_ns(void) {
    static uint64_t fake_ns = 1000000000ULL;
    fake_ns += 16666666ULL;
    return fake_ns;
}
uint64_t runtime_output_size_current(void) { return ((uint64_t)1080 << 32) | 1920; }
uint64_t dm_nvn_frame_count(void) { return 0; }
int fps_overlay_toggle_hints(void) { return 0; }
int hud_compact(void) { return 0; }
int hud_snapshot(int line, char *out, size_t n, int *highlight) { (void)line; (void)out; (void)n; (void)highlight; return 0; }
int mfx_enabled(void) { return 0; }
int mfxup_output_enabled(void) { return 0; }
int runtime_core_away(void) { return 0; }
void runtime_core_back(int *away) { (void)away; }
uint64_t runtime_desired_language(void) { return 0; }
int runtime_ipc_new_session(const char *name, void *handler, void *close_fn, void *ctx) {
    (void)name; (void)handler; (void)close_fn; (void)ctx; return 1;
}
void runtime_ipc_register(const char *name, void *handler) { (void)name; (void)handler; }
void *ipc_arg(void *rq, int idx, size_t sz) { (void)rq; (void)idx; (void)sz; return NULL; }
void *ipc_guest(void *rq, int idx, size_t sz) { (void)rq; (void)idx; (void)sz; return NULL; }
void *ipc_out(void *rs, int idx, size_t sz) { (void)rs; (void)idx; (void)sz; return NULL; }
void ipc_unimplemented(void *s, void *rq) { (void)s; (void)rq; }

/* Subsystem overrides */
void *runtime_front_override(const char *name);
void *runtime_game_override(const char *name);
void *runtime_applet_override(const char *name);

void *runtime_override(const char *name) {
    void *g = runtime_game_override(name);
    if (g) return g;
    void *a = runtime_applet_override(name);
    if (a) return a;
    void *f = runtime_front_override(name);
    return f;
}

typedef struct {
    int64_t status;
    uint64_t frame_number;
    int64_t presentation_timestamp;
    int64_t vsync_timestamp;
    int64_t duration;
} vi_frame_info_t;

typedef struct {
    uint32_t category;
    uint32_t number;
} err_error_code_t;

#define RESULT(module, description) ((uint32_t)(module) | ((uint32_t)(description) << 9))
#define NIFM_UNAVAILABLE RESULT(110, 300)

int main(void) {
    printf("[gaps1] starting gaps 1 overrides test harness\n");

    /* =========================================================================
     * 1. Check override lookup registration via runtime_override
     * ========================================================================= */
    void *fn_vi_frame_num = runtime_override("_ZN2nn2vi20GetLatestFrameNumberEPmPKNS0_5LayerE");
    void *fn_vi_list_hist = runtime_override("_ZN2nn2vi16ListFrameHistoryEPNS0_9FrameInfoEiPKNS0_5LayerE");
    void *fn_nifm_submit = runtime_override("_ZN2nn4nifm20SubmitNetworkRequestEv");
    void *fn_nifm_on_hold = runtime_override("_ZN2nn4nifm22IsNetworkRequestOnHoldEv");
    void *fn_nifm_ip = runtime_override("_ZN2nn4nifm26GetCurrentPrimaryIpAddressEP7in_addr");
    void *fn_err_show = runtime_override("_ZN2nn3err9ShowErrorENS0_9ErrorCodeE");

    if (!fn_vi_frame_num) { fprintf(stderr, "FAIL: GetLatestFrameNumber not found in runtime_override\n"); return 1; }
    if (!fn_vi_list_hist) { fprintf(stderr, "FAIL: ListFrameHistory not found in runtime_override\n"); return 1; }
    if (!fn_nifm_submit) { fprintf(stderr, "FAIL: SubmitNetworkRequest not found in runtime_override\n"); return 1; }
    if (!fn_nifm_on_hold) { fprintf(stderr, "FAIL: IsNetworkRequestOnHold not found in runtime_override\n"); return 1; }
    if (!fn_nifm_ip) { fprintf(stderr, "FAIL: GetCurrentPrimaryIpAddressEP7in_addr not found in runtime_override\n"); return 1; }
    if (!fn_err_show) { fprintf(stderr, "FAIL: ShowError(ErrorCode) not found in runtime_override\n"); return 1; }

    /* =========================================================================
     * 2. VI: GetLatestFrameNumber and ListFrameHistory
     * ========================================================================= */
    void (*vi_init)(void) = (void (*)(void))runtime_override("_ZN2nn2vi10InitializeEv");
    uint32_t (*open_disp)(void **) = (uint32_t (*)(void **))runtime_override("_ZN2nn2vi18OpenDefaultDisplayEPPNS0_7DisplayE");
    uint32_t (*create_layer)(void **, void *, const void *) = (uint32_t (*)(void **, void *, const void *))runtime_override("_ZN2nn2vi11CreateLayerEPPNS0_5LayerEPNS0_7DisplayEPKNS0_21LayerCreationSettingsE");
    void (*destroy_layer)(void *) = (void (*)(void *))runtime_override("_ZN2nn2vi12DestroyLayerEPNS0_5LayerE");

    assert(vi_init && open_disp && create_layer && destroy_layer);
    vi_init();
    void *disp = NULL;
    assert(open_disp(&disp) == 0 && disp != NULL);
    void *layer = NULL;
    assert(create_layer(&layer, disp, NULL) == 0 && layer != NULL);

    uint32_t (*get_latest_frame_num)(uint64_t *, const void *) =
        (uint32_t (*)(uint64_t *, const void *))fn_vi_frame_num;
    int (*list_frame_history)(vi_frame_info_t *, int, const void *) =
        (int (*)(vi_frame_info_t *, int, const void *))fn_vi_list_hist;

    /* Struct size verification: FrameInfo must be 0x28 (40 bytes) */
    assert(sizeof(vi_frame_info_t) == 0x28);

    /* Invalid arguments */
    uint64_t frame_no = 0xdeadbeef;
    assert(get_latest_frame_num(NULL, layer) != 0);
    assert(get_latest_frame_num(&frame_no, NULL) != 0);
    assert(get_latest_frame_num(&frame_no, (void *)0x12345) != 0);

    vi_frame_info_t hist[8];
    memset(hist, 0, sizeof hist);
    assert(list_frame_history(NULL, 8, layer) == 0);
    assert(list_frame_history(hist, 0, layer) == 0);
    assert(list_frame_history(hist, -1, layer) == 0);
    assert(list_frame_history(hist, 8, NULL) == 0);
    assert(list_frame_history(hist, 8, (void *)0x12345) == 0);

    /* GetLatestFrameNumber is the queued frame number: 0x1672 before the first nvnQueuePresentTexture */
    uint32_t res0 = get_latest_frame_num(&frame_no, layer);
    assert(res0 == 0x1672);

    /* A frame shown on screen is not a queued frame */
    extern void front_frame_presented(void);
    front_frame_presented();
    assert(get_latest_frame_num(&frame_no, layer) == 0x1672);

    /* 3 frames queued by the game */
    extern void front_frame_queued(void);
    front_frame_queued();
    front_frame_queued();
    front_frame_queued();
    frame_no = 0;
    uint32_t res3 = get_latest_frame_num(&frame_no, layer);
    assert(res3 == 0);
    assert(frame_no == 3);

    /* No compositor history on the host: 0 entries, nothing written */
    memset(hist, 0xab, sizeof hist);
    assert(list_frame_history(hist, 8, layer) == 0);
    assert(((unsigned char *)hist)[0] == 0xab);

    destroy_layer(layer);

    /* =========================================================================
     * 3. NIFM: SubmitNetworkRequest, IsNetworkRequestOnHold, GetCurrentPrimaryIpAddress
     * ========================================================================= */
    uint32_t (*submit_net_req)(void) = (uint32_t (*)(void))fn_nifm_submit;
    uint8_t (*is_req_on_hold)(void) = (uint8_t (*)(void))fn_nifm_on_hold;
    uint32_t (*get_primary_ip)(struct in_addr *) = (uint32_t (*)(struct in_addr *))fn_nifm_ip;

    /* SubmitNetworkRequest does not block and returns 0 (offline accepted) */
    uint32_t submit_res = submit_net_req();
    assert(submit_res == 0);

    /* IsNetworkRequestOnHold returns 0 (false) */
    uint8_t on_hold = is_req_on_hold();
    assert(on_hold == 0);

    /* GetCurrentPrimaryIpAddress writes 0.0.0.0 and returns NIFM_UNAVAILABLE */
    struct in_addr ip;
    ip.s_addr = 0x12345678;
    uint32_t ip_res = get_primary_ip(&ip);
    assert(ip_res == NIFM_UNAVAILABLE);
    assert(ip.s_addr == 0); /* 0.0.0.0 */

    /* Null pointer check */
    uint32_t ip_null_res = get_primary_ip(NULL);
    assert(ip_null_res == NIFM_UNAVAILABLE);

    /* =========================================================================
     * 4. ERR: ShowError(ErrorCode)
     * ========================================================================= */
    assert(sizeof(err_error_code_t) == 8);
    void (*show_error_fn)(err_error_code_t) = (void (*)(err_error_code_t))fn_err_show;

    err_error_code_t err;
    err.category = 2307;
    err.number = 2118;
    /* Must execute without aborting */
    show_error_fn(err);

    printf("ALL_GAPS1_OVERRIDES_OK\n");
    return 0;
}
