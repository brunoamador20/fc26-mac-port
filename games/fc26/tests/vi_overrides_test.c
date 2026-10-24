/* Synthetic test harness for nn::vi overrides in FC 26 runtime:
   ListDisplays, CreateLayer (with settings), DestroyLayer, SetLayerCrop, CloseDisplay, Finalize. */
#include "runtime.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <unistd.h>
#include <sys/wait.h>

/* Minimal stubs required to link frontend.m standalone */
void hle_bind_system_event(void *ev, int autoclear) { (void)ev; (void)autoclear; }
void hle_clear_system_event(void *ev) { (void)ev; }
void hle_signal_system_event(void *ev) { (void)ev; }
int runtime_fs_save_busy(void) { return 0; }
void runtime_gamepad_start(void) {}
void runtime_input_clear(void) {}
void runtime_input_key(unsigned code, int down) { (void)code; (void)down; }
uint64_t runtime_now_ns(void) { return 1000000ULL; }
void runtime_oe_push_message(uint32_t msg) { (void)msg; }
uint64_t runtime_output_size_current(void) { return ((uint64_t)1080 << 32) | 1920; }
uint64_t dm_nvn_frame_count(void) { return 0; }
int fps_overlay_toggle_hints(void) { return 0; }
int hud_compact(void) { return 0; }
int hud_snapshot(int line, char *out, size_t n, int *highlight) { (void)line; (void)out; (void)n; (void)highlight; return 0; }
int mfx_enabled(void) { return 0; }
int mfxup_output_enabled(void) { return 0; }

typedef struct {
    char name[0x40];
    uint8_t has_layer_limit;
    uint8_t reserved[7];
    int64_t max_layers;
    int64_t max_width;
    int64_t max_height;
} DisplayInfo;

int main(int argc, char **argv) {
    if (argc > 1 && !strcmp(argv[1], "--child-second-layer")) {
        /* Child process: tests that requesting a 2nd layer fails with runtime_missing/runtime_fail */
        void (*vi_init)(void) = (void (*)(void))runtime_front_override("_ZN2nn2vi10InitializeEv");
        uint32_t (*open_disp)(void **) = (uint32_t (*)(void **))runtime_front_override("_ZN2nn2vi18OpenDefaultDisplayEPPNS0_7DisplayE");
        uint32_t (*create_layer)(void **, void *, const void *) = (uint32_t (*)(void **, void *, const void *))runtime_front_override("_ZN2nn2vi11CreateLayerEPPNS0_5LayerEPNS0_7DisplayEPKNS0_21LayerCreationSettingsE");
        if (!vi_init || !open_disp || !create_layer) exit(2);
        vi_init();
        void *disp = NULL;
        open_disp(&disp);
        void *layer1 = NULL;
        uint32_t res1 = create_layer(&layer1, disp, NULL);
        assert(res1 == 0 && layer1 != NULL);
        /* Second layer creation MUST fail and exit process via runtime_fail */
        void *layer2 = NULL;
        create_layer(&layer2, disp, NULL);
        /* If we reached here, it failed to stop! */
        exit(0);
    }

    /* 1. ListDisplays */
    int (*list_displays)(DisplayInfo *, int) = (int (*)(DisplayInfo *, int))runtime_front_override("_ZN2nn2vi12ListDisplaysEPNS0_11DisplayInfoEi");
    if (!list_displays) {
        fprintf(stderr, "FAIL: _ZN2nn2vi12ListDisplaysEPNS0_11DisplayInfoEi not found in runtime_front_override\n");
        return 1;
    }

    /* Invalid parameters return 0 */
    assert(list_displays(NULL, 1) == 0);
    DisplayInfo info;
    memset(&info, 0xaa, sizeof info);
    assert(list_displays(&info, 0) == 0);
    assert(list_displays(&info, -1) == 0);

    /* Valid call */
    int count = list_displays(&info, 1);
    assert(count == 1);
    assert(strcmp(info.name, "Default") == 0);
    assert(info.has_layer_limit == 1);
    assert(info.max_layers == 1);
    assert(info.max_width == 1920);
    assert(info.max_height == 1080);
    for (int i = 0; i < 7; i++) {
        assert(info.reserved[i] == 0);
    }

    /* 2. Overrides existence checks */
    void (*vi_init)(void) = (void (*)(void))runtime_front_override("_ZN2nn2vi10InitializeEv");
    uint32_t (*open_disp)(void **) = (uint32_t (*)(void **))runtime_front_override("_ZN2nn2vi18OpenDefaultDisplayEPPNS0_7DisplayE");
    uint32_t (*create_layer)(void **, void *, const void *) = (uint32_t (*)(void **, void *, const void *))runtime_front_override("_ZN2nn2vi11CreateLayerEPPNS0_5LayerEPNS0_7DisplayEPKNS0_21LayerCreationSettingsE");
    void (*destroy_layer)(void *) = (void (*)(void *))runtime_front_override("_ZN2nn2vi12DestroyLayerEPNS0_5LayerE");
    void (*set_crop)(void *, int, int, int, int) = (void (*)(void *, int, int, int, int))runtime_front_override("_ZN2nn2vi12SetLayerCropEPNS0_5LayerEiiii");
    void (*close_disp)(void *) = (void (*)(void *))runtime_front_override("_ZN2nn2vi12CloseDisplayEPNS0_7DisplayE");
    void (*finalize)(void) = (void (*)(void))runtime_front_override("_ZN2nn2vi8FinalizeEv");
    void *latest_frame = runtime_front_override("_ZN2nn2vi20GetLatestFrameNumberEPmPKNS0_5LayerE");
    void *list_hist = runtime_front_override("_ZN2nn2vi16ListFrameHistoryEPNS0_9FrameInfoEiPKNS0_5LayerE");

    if (!vi_init) { fprintf(stderr, "FAIL: Initialize not found\n"); return 1; }
    if (!open_disp) { fprintf(stderr, "FAIL: OpenDefaultDisplay not found\n"); return 1; }
    if (!create_layer) { fprintf(stderr, "FAIL: CreateLayer (3 args) not found\n"); return 1; }
    if (!destroy_layer) { fprintf(stderr, "FAIL: DestroyLayer not found\n"); return 1; }
    if (!set_crop) { fprintf(stderr, "FAIL: SetLayerCrop not found\n"); return 1; }
    if (!close_disp) { fprintf(stderr, "FAIL: CloseDisplay not found\n"); return 1; }
    if (!finalize) { fprintf(stderr, "FAIL: Finalize not found\n"); return 1; }
    if (!latest_frame) { fprintf(stderr, "FAIL: GetLatestFrameNumber not found\n"); return 1; }
    if (!list_hist) { fprintf(stderr, "FAIL: ListFrameHistory not found\n"); return 1; }

    /* Initialize and OpenDefaultDisplay */
    vi_init();
    void *disp = NULL;
    uint32_t r_open = open_disp(&disp);
    assert(r_open == 0 && disp != NULL);

    /* 3. Layer lifecycle: create -> destroy -> create again */
    void *layer = NULL;
    uint32_t r_lay1 = create_layer(&layer, disp, NULL);
    assert(r_lay1 == 0 && layer != NULL);

    /* SetLayerCrop on active layer */
    set_crop(layer, 0, 0, 1920, 1080);

    /* Destroy the layer */
    destroy_layer(layer);

    /* Re-creation succeeds after destroy */
    void *layer_recreated = NULL;
    uint32_t r_lay2 = create_layer(&layer_recreated, disp, NULL);
    assert(r_lay2 == 0 && layer_recreated == layer);

    /* 4. Second layer failure check in child process */
    pid_t pid = fork();
    if (pid == 0) {
        char *child_argv[] = { argv[0], "--child-second-layer", NULL };
        execv(argv[0], child_argv);
        exit(127);
    }
    int status = 0;
    waitpid(pid, &status, 0);
    assert(WIFEXITED(status));
    assert(WEXITSTATUS(status) == 1); /* exited via runtime_fail */

    /* 5. Clean close and finalize */
    destroy_layer(layer_recreated);
    close_disp(disp);
    finalize();

    printf("ALL_VI_OVERRIDES_OK\n");
    return 0;
}
