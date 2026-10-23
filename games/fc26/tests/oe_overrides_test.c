/* Synthetic test harness for nn::oe overrides in FC 26 runtime:
   GetDefaultDisplayResolution, GetDefaultDisplayResolutionChangeEvent,
   GetPerformanceConfiguration, SetPerformanceConfiguration,
   GetPseudoDeviceId, GetDisplayVersion, GetNotificationMessageEvent,
   DisableScreenShot, EnterExitRequestHandlingSection, LeaveExitRequestHandlingSection. */
#include "runtime.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>

/* Minimal stubs required to link services.c / applet_host.c / etc. standalone */
pthread_key_t runtime_keys[8];
static uint32_t fake_create_system_event(void *ev, int autoclear, int inter_process) {
    (void)autoclear; (void)inter_process;
    memset(ev, 0, 0x38);
    ((uint8_t *)ev)[0x28] = 2; /* initialized */
    *(uint32_t *)((uint8_t *)ev + 0x14) = 0x2001; /* write handle */
    *(uint32_t *)((uint8_t *)ev + 0x18) = 0x2002; /* read handle */
    return 0;
}
static uint32_t fake_get_writable_handle(const void *ev) {
    return *(const uint32_t *)((const uint8_t *)ev + 0x14);
}
void *runtime_symbol(const char *name) {
    if (strstr(name, "CreateSystemEvent")) return (void *)fake_create_system_event;
    if (strstr(name, "GetWritableHandleOfSystemEvent")) return (void *)fake_get_writable_handle;
    return NULL;
}
void runtime_startup_checkpoint(uintptr_t lr) { (void)lr; }
void runtime_startup_checkpoint_nnmain(uintptr_t lr) { (void)lr; }
int runtime_front_focus(void) { return 1; }
void runtime_fs_init(void) {}
void *runtime_offline_applet_override(const char *name) { (void)name; return NULL; }
void *runtime_input_override(const char *name) { (void)name; return NULL; }
void *runtime_font_override(const char *name) { (void)name; return NULL; }
void *runtime_codec_override(const char *name) { (void)name; return NULL; }
void *runtime_movie_override(const char *name) { (void)name; return NULL; }
void *runtime_time_override(const char *name) { (void)name; return NULL; }
void *runtime_swkbd_override(const char *name) { (void)name; return NULL; }
void *runtime_account_override(const char *name) { (void)name; return NULL; }
void *runtime_fs_override(const char *name) { (void)name; return NULL; }
void *runtime_front_override(const char *name) { (void)name; return NULL; }
void *runtime_gfx_override(const char *name) { (void)name; return NULL; }
void *runtime_game_override(const char *name) { (void)name; return NULL; }
int runtime_ipc_svc(unsigned num, uint64_t *r) { (void)num; (void)r; return 0; }
void memory_init(void) {}
uint64_t runtime_module_permission(uint64_t a, uint64_t b, unsigned c) { (void)a; (void)b; (void)c; return 0; }
uint64_t runtime_module_lock_permission(uint64_t a, uint64_t b, unsigned c, unsigned d) { (void)a; (void)b; (void)c; (void)d; return 0; }
void guest_guard_check(void) {}
void dm_thread_enter(void) {}
void *memory_gap_find(uint64_t a) { (void)a; return NULL; }
int ro_module_query(uint64_t a, void *b) { (void)a; (void)b; return 0; }
int ro_module_regions(void *a, int b) { (void)a; (void)b; return 0; }
uint64_t runtime_image_bytes(void) { return 0; }
int runtime_module_patch_query(uint64_t a, uint64_t *base, uint64_t *size, unsigned *state, unsigned *permission, unsigned *attribute) { (void)a; (void)base; (void)size; (void)state; (void)permission; (void)attribute; return 0; }
int runtime_module_query(uint64_t a, uint64_t *base, uint64_t *size, unsigned *state, unsigned *permission, unsigned *attribute) { (void)a; (void)base; (void)size; (void)state; (void)permission; (void)attribute; return 0; }
size_t runtime_module_regions(MemoryRegion *out, size_t max_count) { (void)out; (void)max_count; return 0; }
uint64_t runtime_now_ns(void) { return 1000000ULL; }
uint64_t runtime_output_res_extra_bytes(void) { return 0; }
void runtime_thread_init(void) {}
void runtime_thread_leave(void) {}
void runtime_trace_guest(uint64_t fp, uint64_t lr) { (void)fp; (void)lr; }

typedef struct { uint8_t data[16]; } Uuid;
typedef struct { char version[16]; } DisplayVersion;

uint32_t svc_thread_main_init(void);

int main(int argc, char **argv) {
    svc_thread_main_init();
    int test_handheld = (argc > 1 && !strcmp(argv[1], "--handheld"));

    /* 1. GetDefaultDisplayResolution */
    void (*get_res)(int *, int *) = (void (*)(int *, int *))runtime_override("_ZN2nn2oe27GetDefaultDisplayResolutionEPiS1_");
    if (!get_res) {
        fprintf(stderr, "FAIL: _ZN2nn2oe27GetDefaultDisplayResolutionEPiS1_ not found in runtime_override\n");
        return 1;
    }
    int w = 0, h = 0;
    get_res(&w, &h);
    if (test_handheld) {
        assert(w == 1280 && h == 720);
    } else {
        assert(w == 1920 && h == 1080);
    }

    /* 2. GetDefaultDisplayResolutionChangeEvent */
    void (*get_res_ev)(void *) = (void (*)(void *))runtime_override("_ZN2nn2oe38GetDefaultDisplayResolutionChangeEventEPNS_2os11SystemEventE");
    if (!get_res_ev) {
        fprintf(stderr, "FAIL: _ZN2nn2oe38GetDefaultDisplayResolutionChangeEventEPNS_2os11SystemEventE not found\n");
        return 1;
    }
    uint8_t ev_buf[0x40];
    memset(ev_buf, 0, sizeof ev_buf);
    get_res_ev(ev_buf);
    assert(ev_buf[0x28] == 2); /* properly bound */

    /* 3. PerformanceConfiguration: default and set */
    int (*get_perf_cfg)(int) = (int (*)(int))runtime_override("_ZN2nn2oe27GetPerformanceConfigurationENS0_15PerformanceModeE");
    void (*set_perf_cfg)(int, int) = (void (*)(int, int))runtime_override("_ZN2nn2oe27SetPerformanceConfigurationENS0_15PerformanceModeEi");
    if (!get_perf_cfg) {
        fprintf(stderr, "FAIL: _ZN2nn2oe27GetPerformanceConfigurationENS0_15PerformanceModeE not found\n");
        return 1;
    }
    assert(set_perf_cfg != NULL);
    /* Defaults proven: mode 0 = 0x10001, mode 1 = 0x20003 */
    assert(get_perf_cfg(0) == 0x00010001);
    assert(get_perf_cfg(1) == 0x00020003);
    /* After Set: */
    set_perf_cfg(0, 0x00020004);
    assert(get_perf_cfg(0) == 0x00020004);
    set_perf_cfg(1, 0x92220008);
    assert(get_perf_cfg(1) == (int)0x92220008);

    /* 4. GetPseudoDeviceId */
    void (*get_pseudo_dev)(Uuid *) = (void (*)(Uuid *))runtime_override("_ZN2nn2oe17GetPseudoDeviceIdEPNS_4util4UuidE");
    if (!get_pseudo_dev) {
        fprintf(stderr, "FAIL: _ZN2nn2oe17GetPseudoDeviceIdEPNS_4util4UuidE not found\n");
        return 1;
    }
    Uuid id1 = {{0}}, id2 = {{0}};
    get_pseudo_dev(&id1);
    int non_zero = 0;
    for (int i = 0; i < 16; i++) if (id1.data[i] != 0) non_zero = 1;
    assert(non_zero);
    get_pseudo_dev(&id2);
    assert(memcmp(id1.data, id2.data, 16) == 0);

    /* Verify persistent file content matches */
    const char *pdir = getenv("TOTK_PROFILE_DIR");
    if (!pdir) pdir = "user-data";
    char uuid_path[1024];
    snprintf(uuid_path, sizeof uuid_path, "%s/pseudo_device.uuid", pdir);
    int fd = open(uuid_path, O_RDONLY);
    assert(fd >= 0);
    Uuid file_id = {{0}};
    assert(read(fd, &file_id, 16) == 16);
    close(fd);
    assert(memcmp(id1.data, file_id.data, 16) == 0);

    /* 5. GetDisplayVersion */
    void (*get_disp_ver)(DisplayVersion *) = (void (*)(DisplayVersion *))runtime_override("_ZN2nn2oe17GetDisplayVersionEPNS0_14DisplayVersionE");
    if (!get_disp_ver) {
        fprintf(stderr, "FAIL: _ZN2nn2oe17GetDisplayVersionEPNS0_14DisplayVersionE not found\n");
        return 1;
    }
    DisplayVersion dv = {{0}};
    get_disp_ver(&dv);
    assert(strcmp(dv.version, "1.89.6e65") == 0);   /* the update's control.nacp (story H1), not the base's 1.0.0 */

    /* 6. Void applet controls: DisableScreenShot, Enter/LeaveExitRequestHandlingSection */
    void (*disable_ss)(void) = (void (*)(void))runtime_override("_ZN2nn2oe17DisableScreenShotEv");
    void (*enter_exit)(void) = (void (*)(void))runtime_override("_ZN2nn2oe31EnterExitRequestHandlingSectionEv");
    void (*leave_exit)(void) = (void (*)(void))runtime_override("_ZN2nn2oe31LeaveExitRequestHandlingSectionEv");
    if (!disable_ss || !enter_exit || !leave_exit) {
        fprintf(stderr, "FAIL: DisableScreenShot or Enter/LeaveExitRequest not found\n");
        return 1;
    }
    disable_ss();
    enter_exit();
    leave_exit();

    /* 7. GetNotificationMessageEvent */
    void *(*get_notif_ev)(void) = (void *(*)(void))runtime_override("_ZN2nn2oe27GetNotificationMessageEventEv");
    if (!get_notif_ev) {
        fprintf(stderr, "FAIL: _ZN2nn2oe27GetNotificationMessageEventEv not found\n");
        return 1;
    }
    void *notif_ev = get_notif_ev();
    assert(notif_ev != NULL);

    printf("ALL_OE_OVERRIDES_OK\n");
    return 0;
}
