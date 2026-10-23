/* The offline services of story 4 answered without the game (runtime/offline_services.c, offline_applets.c, hwopus.c):
   requests are built as the SDK's CMIF client builds them (HIPC header, buffer descriptors, copy handles, the CMIF
   header and arguments) and sent through the same SVC entry the rewritten code reaches (SendSyncRequest on the thread's
   message buffer, runtime/ipc.c). hwopus decodes real Opus frames made here with libopus's encoder.
   Usage: offline_ipc all | command <service> <id> | ldn-command <id> | hwopus-range
     all            every answer of docs/SERVICOS_NUVEM.md's table, checked; prints "ok: ..." lines, exit 0
     command        an unknown command of a service (sm name) stops with its name and number (exit 1)
     ldn-command    the same for IUserLocalCommunicationService, reached through ldn:u
     hwopus-range   a frame whose final range does not match stops the runtime (exit 1)
   Stops go through the runtime's own runtime_fail / runtime_missing (missing.c). */
#include "runtime.h"
#include "ipc.h"
#include <opus.h>
#include <opus_multistream.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>

/* ---------- what threads.c, loader.c and the graphics bridge give the IPC layer in the runtime ---------- */
pthread_key_t runtime_keys[8];
enum { KIND_EVENT_W = 2, KIND_EVENT_R = 3, HANDLES = 256 };
typedef struct { int signaled; } Event;
static void *objects[HANDLES];
static int kinds[HANDLES];
static unsigned nobjects;
uint32_t runtime_handle_new(int session, void *obj) {
    if (nobjects == HANDLES) runtime_fail("test handle table full");
    objects[nobjects] = obj; kinds[nobjects] = session;
    return 0x100 + nobjects++;
}
void *runtime_handle_get(uint32_t h, int session) { h -= 0x100; return h < nobjects && kinds[h] == session ? objects[h] : NULL; }
void *runtime_handle_take_session(uint32_t h) { void *s = runtime_handle_get(h, 1); if (s) objects[h - 0x100] = NULL; return s; }
uint32_t runtime_event_new(void) { Event *e = calloc(1, sizeof *e); if (!e) runtime_fail("test event"); return runtime_handle_new(KIND_EVENT_W, e); }
uint32_t runtime_event_readable(uint32_t w) {
    Event *e = runtime_handle_get(w, KIND_EVENT_W); if (!e) runtime_fail("test event handle");
    return runtime_handle_new(KIND_EVENT_R, e);
}
void runtime_event_signal(uint32_t w) { Event *e = runtime_handle_get(w, KIND_EVENT_W); if (!e) runtime_fail("test event handle"); e->signaled = 1; }
void runtime_trace_guest(uint64_t fp, uint64_t lr) { (void)fp; (void)lr; }
void dm_guest_write_prepare(void *addr, size_t n) { (void)addr; (void)n; }

static int failures;
#define CHECK(cond, ...) do { if (cond) { printf("ok: "); printf(__VA_ARGS__); putchar('\n'); } \
                              else { printf("FAIL: "); printf(__VA_ARGS__); printf("  (%s, line %d)\n", #cond, __LINE__); failures++; } } while (0)

/* Buffers the descriptors can address: an X descriptor holds 42 address bits, so they live in a low mapping. */
static uint8_t *arena; static size_t arena_used;
static void *low(size_t n) {
    if (!arena) {
        arena = mmap((void *)(uintptr_t)0x40000000, 1 << 22, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (arena == MAP_FAILED || (uintptr_t)arena + (1 << 22) > (1ULL << 42)) runtime_fail("test arena");
    }
    n = (n + 15) & ~(size_t)15;
    if (arena_used + n > (1 << 22)) runtime_fail("test arena full");
    void *p = arena + arena_used; arena_used += n; memset(p, 0, n); return p;
}

/* ---------- requests and replies (libnx hipc.h / cmif.h layout, as runtime/ipc.c parses it) ---------- */
static uint32_t msg[64] __attribute__((aligned(16)));
typedef struct { const void *p; uint64_t size; } Buf;
typedef struct { Buf x, a, b, c; uint32_t copy; int pid; } Extra;   /* at most one of each: what these commands use */
typedef struct { uint32_t result; uint8_t data[64]; uint32_t copy[8], move[8]; unsigned ncopy, nmove, nxout; } Reply;

static void request(uint32_t cmd, const void *args, unsigned n, const Extra *e) {
    static const Extra none;
    if (!e) e = &none;
    memset(msg, 0, sizeof msg);
    unsigned nx = e->x.size != 0, na = e->a.size != 0, nb = e->b.size != 0, nc = e->c.size != 0, special = e->pid || e->copy;
    msg[0] = 4 | nx << 16 | na << 20 | nb << 24;
    uint32_t *p = msg + 2;
    if (special) {
        *p++ = (e->pid ? 1u : 0u) | (e->copy ? 1u : 0u) << 1;
        if (e->pid) p += 2;                                        /* the kernel fills the pid in */
        if (e->copy) *p++ = e->copy;
    }
    if (nx) {
        uint64_t a = (uintptr_t)e->x.p;
        p[0] = (uint32_t)(((a >> 36) & 0x3f) << 6 | ((a >> 32) & 0xf) << 12 | e->x.size << 16); p[1] = (uint32_t)a; p += 2;
    }
    const Buf *ab[2] = {&e->a, &e->b};
    for (int k = 0; k < 2; k++) if (ab[k]->size) {
        uint64_t a = (uintptr_t)ab[k]->p, s = ab[k]->size;
        p[0] = (uint32_t)s; p[1] = (uint32_t)a; p[2] = (uint32_t)(((a >> 36) & 0x3fffff) << 2 | ((s >> 32) & 0xf) << 24 | ((a >> 32) & 0xf) << 28);
        p += 3;
    }
    uint8_t *words = (uint8_t *)p, *payload = (uint8_t *)msg + (((words - (uint8_t *)msg) + 15) & ~15);
    unsigned ndata = (unsigned)((payload - words) + 16 + n + 16 + 3) / 4;
    uint32_t h[4] = {0x49434653u, 0, cmd, 0};
    memcpy(payload, h, 16);
    if (n) memcpy(payload + 16, args, n);
    msg[1] = ndata | (nc ? 2u : 0u) << 10 | special << 31;
    if (nc) {
        uint32_t *recv = p + ndata; uint64_t a = (uintptr_t)e->c.p;
        recv[0] = (uint32_t)a; recv[1] = (uint32_t)((a >> 32) & 0xffff) | (uint32_t)(e->c.size << 16);
    }
}
static Reply call(uint32_t handle, uint32_t cmd, const void *args, unsigned n, const Extra *e) {
    request(cmd, args, n, e);
    uint64_t r[31] = {0}; r[0] = handle;
    if (!runtime_ipc_svc(0x21, r) || r[0]) { fprintf(stderr, "SendSyncRequest %#x: %#llx\n", handle, (unsigned long long)r[0]); exit(1); }
    Reply rp; memset(&rp, 0, sizeof rp);
    rp.nxout = (msg[0] >> 16) & 0xf;
    const uint32_t *p = msg + 2;
    if (msg[1] >> 31) {
        uint32_t hd = *p++; rp.ncopy = (hd >> 1) & 15; rp.nmove = (hd >> 5) & 15;
        for (unsigned i = 0; i < rp.ncopy; i++) rp.copy[i] = *p++;
        for (unsigned i = 0; i < rp.nmove; i++) rp.move[i] = *p++;
    }
    p += 2 * rp.nxout;
    const uint8_t *payload = (const uint8_t *)msg + ((((const uint8_t *)p - (const uint8_t *)msg) + 15) & ~15);
    uint32_t h[4]; memcpy(h, payload, 16);
    if (h[0] != 0x4f434653u) { fprintf(stderr, "reply magic %#x\n", h[0]); exit(1); }
    rp.result = h[2];
    memcpy(rp.data, payload + 16, sizeof rp.data);
    return rp;
}
static uint32_t u32_at(const Reply *r, unsigned off) { uint32_t v; memcpy(&v, r->data + off, 4); return v; }
static uint32_t sm_handle;
static uint32_t open_service(const char *name) {
    if (!sm_handle) {
        char port[16] = "sm:";
        uint64_t r[31] = {0}; r[1] = (uintptr_t)port;
        if (!runtime_ipc_svc(0x1f, r) || r[0]) runtime_fail("test ConnectToNamedPort sm:");
        sm_handle = (uint32_t)r[1];
        call(sm_handle, 0, NULL, 0, NULL);                         /* RegisterClient */
    }
    char n[8] = {0}; memcpy(n, name, strnlen(name, 8));
    Reply r = call(sm_handle, 1, n, 8, NULL);
    if (r.result || r.nmove != 1) { fprintf(stderr, "GetServiceHandle %s: no handle\n", name); exit(1); }
    return r.move[0];
}
/* A command that makes an object: the object's session handle. */
static uint32_t object(uint32_t handle, uint32_t cmd, const void *args, unsigned n, const Extra *e) {
    Reply r = call(handle, cmd, args, n, e);
    if (r.result || r.nmove != 1) { fprintf(stderr, "command %u made no object (result %#x)\n", cmd, r.result); exit(1); }
    return r.move[0];
}
static int event_readable(uint32_t h) { return runtime_handle_get(h, KIND_EVENT_R) != NULL; }
static int event_signaled(uint32_t h) { Event *e = runtime_handle_get(h, KIND_EVENT_R); return e && e->signaled; }

/* ---------- aoc:u ---------- */
static void aoc(void) {
    uint32_t s = open_service("aoc:u");
    uint64_t pid = 0;
    Reply r = call(s, 2, &pid, 8, &(Extra){.pid = 1});
    CHECK(!r.result && u32_at(&r, 0) == 0, "aoc:u CountAddOnContent = 0");
    uint32_t *list = low(64 * 4); list[0] = 0xdeadbeef;
    struct { uint32_t offset, count; uint64_t pid; } la = {0, 64, 0};
    r = call(s, 3, &la, sizeof la, &(Extra){.b = {list, 64 * 4}, .pid = 1});
    CHECK(!r.result && u32_at(&r, 0) == 0 && list[0] == 0xdeadbeef, "aoc:u ListAddOnContent = 0, buffer untouched");
    r = call(s, 5, &pid, 8, &(Extra){.pid = 1});
    uint64_t base; memcpy(&base, r.data, 8);
    CHECK(!r.result && base == 0x01004ff021943000ULL, "aoc:u GetAddOnContentBaseId = %016llX", (unsigned long long)base);
    r = call(s, 8, NULL, 0, NULL);
    CHECK(!r.result && r.ncopy == 1 && event_readable(r.copy[0]) && !event_signaled(r.copy[0]), "aoc:u GetAddOnContentListChangedEvent: an event, never signalled");
    r = call(s, 50, &pid, 8, &(Extra){.pid = 1});
    CHECK(!r.result, "aoc:u CheckAddOnContentMountStatus = success");
    uint32_t m = object(s, 100, &pid, 8, &(Extra){.pid = 1});
    r = call(m, 2, NULL, 0, NULL);
    CHECK(!r.result && r.ncopy == 1 && !event_signaled(r.copy[0]), "aoc:u IPurchaseEventManager GetPurchasedEventReadableHandle: never signalled");
}

/* ---------- pctl ---------- */
static void pctl(void) {
    static const char *const names[] = {"pctl", "pctl:a", "pctl:s", "pctl:r"};
    for (unsigned i = 0; i < 4; i++) {
        uint32_t f = open_service(names[i]);
        uint64_t pid = 0;
        uint32_t s = object(f, i % 2 ? 1 : 0, &pid, 8, &(Extra){.pid = 1});
        Reply r = call(s, 1, NULL, 0, NULL);
        int ok = !r.result;
        static const uint32_t granted[] = {1001, 1002, 1003, 1004, 1005, 1013, 1016, 1017, 1018, 1451, 1452};
        for (unsigned k = 0; k < sizeof granted / sizeof *granted; k++) ok &= !call(s, granted[k], NULL, 0, NULL).result;
        CHECK(ok, "%s: Initialize, free communication available (1001/1017/1018), every Confirm*Permission granted", names[i]);
        r = call(s, 1031, NULL, 0, NULL);
        CHECK(!r.result && r.data[0] == 0, "%s IsRestrictionEnabled = false", names[i]);
        r = call(s, 1065, NULL, 0, NULL);
        CHECK(!r.result && r.data[0] == 1, "%s IsStereoVisionPermitted = true", names[i]);
        r = call(s, 1453, NULL, 0, NULL);
        CHECK(!r.result && r.data[0] == 0, "%s IsPlayTimerEnabled = false", names[i]);
        r = call(s, 1432, NULL, 0, NULL);
        CHECK(!r.result && r.ncopy == 1 && !event_signaled(r.copy[0]), "%s GetSynchronizationEvent: never signalled", names[i]);
    }
}

/* ---------- ldn ---------- */
enum { NOT_INITIALIZED = 0x4acb, INVALID_STATE = 0x4ecb, INVALID_ARGUMENT = 0xc0cb, INVALID_PROTOCOL = 0x3acb, WIRELESS_OFF = 0x2ccb };
static uint32_t state_of(uint32_t comm) { Reply r = call(comm, 0, NULL, 0, NULL); return r.result ? 0xffffffffu : u32_at(&r, 0); }
static void ldn(void) {
    uint32_t creator = open_service("ldn:u");
    uint32_t comm = object(creator, 0, NULL, 0, NULL);
    CHECK(state_of(comm) == 0, "ldn:u GetState = None before Initialize");
    Reply r = call(comm, 100, NULL, 0, NULL);
    uint32_t event = r.ncopy ? r.copy[0] : 0;
    CHECK(!r.result && event_readable(event) && !event_signaled(event), "ldn:u GetStateChangeEvent: an event");
    CHECK(call(comm, 300, NULL, 0, NULL).result == NOT_INITIALIZED, "ldn:u OpenStation before Initialize = 2203-0037");
    struct { int32_t version; uint32_t pad; uint64_t pid; } init = {3, 0, 0};
    r = call(comm, 402, &init, sizeof init, &(Extra){.pid = 1});
    CHECK(!r.result && state_of(comm) == 1 && event_signaled(event), "ldn:u InitializeWithVersion(3): Initialized, event signalled");
    uint32_t monitor = object(open_service("ldn:u"), 1, NULL, 0, NULL);
    uint64_t pid = 0;
    CHECK(!call(monitor, 0, &pid, 8, &(Extra){.pid = 1}).result, "ldn:u CreateClientProcessMonitor + RegisterClient");
    uint32_t protocol = 1;
    CHECK(!call(comm, 106, &protocol, 4, NULL).result, "ldn:u SetProtocol(1)");
    protocol = 2;
    CHECK(call(comm, 106, &protocol, 4, NULL).result == INVALID_PROTOCOL, "ldn:u SetProtocol(2) = 2203-0029");
    uint8_t scan_args[0x68] = {0};                                 /* s16 channel, padding, ScanFilter */
    void *nets = low(0x18 * 0x480);
    CHECK(call(comm, 102, scan_args, sizeof scan_args, &(Extra){.b = {nets, 0x18 * 0x480}}).result == INVALID_STATE, "ldn:u Scan while Initialized = 2203-0039");
    CHECK(!call(comm, 300, NULL, 0, NULL).result && state_of(comm) == 4, "ldn:u OpenStation: Station");
    r = call(comm, 102, scan_args, sizeof scan_args, &(Extra){.b = {nets, 0x18 * 0x480}});
    int16_t count; memcpy(&count, r.data, 2);
    CHECK(!r.result && count == 0, "ldn:u Scan (B buffer): no network");
    r = call(comm, 103, scan_args, sizeof scan_args, &(Extra){.c = {nets, 0x480}});
    memcpy(&count, r.data, 2);
    CHECK(!r.result && count == 0 && r.nxout == 1, "ldn:u ScanPrivate (C buffer): no network");
    CHECK(call(comm, 102, scan_args, sizeof scan_args, &(Extra){.b = {nets, 0x100}}).result == INVALID_ARGUMENT, "ldn:u Scan with no room for one NetworkInfo = 2203-0096");
    void *net = low(0x480);
    uint8_t connect_args[0x7c] = {0};                              /* SecurityConfig, UserConfig, s32 version, ConnectOption */
    CHECK(call(comm, 302, connect_args, sizeof connect_args, &(Extra){.x = {net, 0x480}}).result == WIRELESS_OFF, "ldn:u Connect = 2203-0022 (no wireless)");
    CHECK(state_of(comm) == 4, "ldn:u still Station after the failed Connect");
    CHECK(call(comm, 1, NULL, 0, NULL).result == INVALID_STATE, "ldn:u GetNetworkInfo without a network = 2203-0039");
    CHECK(call(comm, 304, NULL, 0, NULL).result == INVALID_STATE, "ldn:u Disconnect without a network = 2203-0039");
    CHECK(!call(comm, 301, NULL, 0, NULL).result && state_of(comm) == 1, "ldn:u CloseStation: Initialized");
    CHECK(!call(comm, 200, NULL, 0, NULL).result && state_of(comm) == 2, "ldn:u OpenAccessPoint: AccessPoint");
    void *adv = low(0x200);
    CHECK(!call(comm, 206, NULL, 0, &(Extra){.a = {adv, 0x100}}).result, "ldn:u SetAdvertiseData (0x100 bytes)");
    CHECK(call(comm, 206, NULL, 0, &(Extra){.a = {adv, 0x200}}).result == INVALID_ARGUMENT, "ldn:u SetAdvertiseData over 0x180 bytes = 2203-0096");
    uint8_t create_args[0x98] = {0};                               /* SecurityConfig, UserConfig, NetworkConfig */
    CHECK(call(comm, 202, create_args, sizeof create_args, NULL).result == WIRELESS_OFF, "ldn:u CreateNetwork = 2203-0022 (no wireless)");
    CHECK(call(comm, 204, NULL, 0, NULL).result == INVALID_STATE, "ldn:u DestroyNetwork without a network = 2203-0039");
    CHECK(!call(comm, 201, NULL, 0, NULL).result && state_of(comm) == 1, "ldn:u CloseAccessPoint: Initialized");
    CHECK(!call(comm, 401, NULL, 0, NULL).result && state_of(comm) == 0, "ldn:u Finalize: None");
    CHECK(call(comm, 401, NULL, 0, NULL).result == NOT_INITIALIZED, "ldn:u Finalize twice = 2203-0037");

    /* ldn:s numbers 402-404 differently; ldn:m reports the shared state; closing without Finalize finalizes. */
    uint32_t sys = object(open_service("ldn:s"), 0, NULL, 0, NULL);
    uint32_t mon = object(open_service("ldn:m"), 0, NULL, 0, NULL);
    CHECK(!call(mon, 100, NULL, 0, NULL).result, "ldn:m IMonitorService Initialize");
    CHECK(!call(sys, 403, &init, sizeof init, &(Extra){.pid = 1}).result && state_of(sys) == 1, "ldn:s InitializeWithVersion (cmd 403): Initialized");
    uint32_t mode = 0;
    CHECK(!call(sys, 402, &mode, 4, NULL).result, "ldn:s SetOperationMode (cmd 402)");
    r = call(mon, 0, NULL, 0, NULL);
    CHECK(!r.result && u32_at(&r, 0) == 1, "ldn:m GetState = Initialized");
    runtime_ipc_session_closed(runtime_handle_get(sys, 1));
    r = call(mon, 0, NULL, 0, NULL);
    CHECK(!r.result && u32_at(&r, 0) == 0, "ldn:s closed without Finalize: None again");
}

/* ---------- nim:eca, nim:ecas ---------- */
static void shop(void) {
    uint32_t eca = open_service("nim:eca");
    uint8_t args[16] = {0};
    uint32_t tmem = runtime_handle_new(0, NULL);
    uint32_t server = object(eca, 0, args, 8, &(Extra){.copy = tmem, .pid = 1});
    Reply r = call(eca, 4, NULL, 0, &(Extra){.pid = 1});
    CHECK(!r.result && r.data[0] == 0, "nim:eca IsLargeResourceAvailable = false");
    CHECK(object(eca, 5, args, 8, &(Extra){.copy = tmem, .pid = 1}) != 0, "nim:eca CreateServerInterface2: an object");
    uint32_t accessor = object(server, 0, args, 1, NULL);
    r = call(accessor, 0, args, 8, NULL);
    CHECK(!r.result && r.ncopy == 1 && r.nmove == 1 && event_signaled(r.copy[0]), "nim:eca CreateAsyncInterface: a signalled event and the object");
    uint32_t async = r.move[0];
    void *path = low(0x100);
    CHECK(!call(async, 4, args, 16, &(Extra){.a = {path, 0x100}}).result, "nim:eca Request accepted");
    CHECK(call(async, 1, NULL, 0, NULL).result == 0x70a4, "nim:eca GetSize = 2164-0056 (internet request not accepted)");
    CHECK(call(async, 2, NULL, 0, &(Extra){.b = {path, 0x100}}).result == 0x70a4, "nim:eca Read = 2164-0056");
    CHECK(call(async, 3, NULL, 0, NULL).result == 0x70a4, "nim:eca GetErrorCode = 2164-0056");
    CHECK(call(async, 5, NULL, 0, NULL).result == 0x70a4, "nim:eca Prepare = 2164-0056");
    CHECK(!call(async, 0, NULL, 0, NULL).result, "nim:eca Cancel");
    uint32_t ecas = open_service("nim:ecas");
    CHECK(!call(ecas, 0, args, 8, &(Extra){.pid = 1}).result && !call(ecas, 1, args, 8, &(Extra){.pid = 1}).result, "nim:ecas (Un)RegisterSpecialClient");
}

/* ---------- applets by name ---------- */
static void applets(void) {
    /* Names as clang++ mangles them (tests/test_offline_services.py checks these strings against the compiler). */
    static const char web[] = "_ZN2nn3web11ShowWebPageEPNS0_18WebPageReturnValueERKNS0_14ShowWebPageArgE";
    uint32_t (*show)(uint8_t *, const void *) = (uint32_t (*)(uint8_t *, const void *))runtime_offline_applet_override(web);
    uint8_t value[16]; memset(value, 0xa5, sizeof value);
    CHECK(show && show(value, NULL) == 0 && value[0] == 0 && value[4] == 0 && value[8] == 0 && value[9] == 0xa5,
          "nn::web::ShowWebPage: Result 0, exit reason 0, empty last URL, nothing written past 9 bytes");
    void *other = runtime_offline_applet_override("_ZN2nn3web11ShowWebPageERKNS0_14ShowWebPageArgE");
    CHECK(other && other != (void *)show && ((uint32_t (*)(void))other)() == 0, "nn::web::ShowWebPage (another overload): Result 0, nothing written");
    void *exit_page = runtime_offline_applet_override("_ZN2nn3web18RequestExitWebPageEv");
    CHECK(exit_page && ((uint32_t (*)(void))exit_page)() == 0, "nn::web::RequestExitWebPage: nothing to close");
    static const char *const shops[] = {
        "_ZN2nn2ec19ShowShopProductListENS_13ApplicationIdE", "_ZN2nn2ec22ShowShopProductDetailsENS_13ApplicationIdENS0_5NsUidE",
        "_ZN2nn2ec24ShowShopAddOnContentListENS_13ApplicationIdE", "_ZN2nn2ec28ShowShopConsumableItemDetailENS_13ApplicationIdENS0_5NsUidE",
        "_ZN2nn2ec22ShowShopEnterCodeSceneEv"};
    int ok = 1;
    for (unsigned i = 0; i < 5; i++) { void *f = runtime_offline_applet_override(shops[i]); ok &= f && ((uint32_t (*)(void))f)() == 0; }
    CHECK(ok, "nn::ec::ShowShop{ProductList,ProductDetails,AddOnContentList,ConsumableItemDetail,EnterCodeScene}: Result 0 at once");
    static const char *const untouched[] = {
        "_ZN2nn3web14ShowWebPageArg14SetCallbackUrlEPKc", "_ZN2nn2ec9MakeNsUidEm", "_ZN2nn2ec19ShopServiceAccessor10InitializeENS0_11ShopServiceE",
        "_ZN2nn2ec33InitializeForShopServiceAccessorsEv", "_ZN2nn3web11ShowWebPagX", "_ZN2nn3ldn4ScanEPNS0_11NetworkInfoEPiiRKNS0_10ScanFilterEi", "nnMain"};
    ok = 1;
    for (unsigned i = 0; i < sizeof untouched / sizeof *untouched; i++) ok &= runtime_offline_applet_override(untouched[i]) == NULL;
    CHECK(ok, "setters, MakeNsUid, ShopServiceAccessor, nn::ldn and other names are left to the sdk");
}

/* ---------- hwopus ---------- */
enum { RATE = 48000, FRAME = 960, FRAMES = 12 };
#define PI 3.14159265358979323846
/* One Nintendo frame: be32 payload size, be32 final range, the packet. */
static size_t frame(uint8_t *out, const uint8_t *packet, int n, uint32_t range) {
    uint8_t h[8] = {(uint8_t)(n >> 24), (uint8_t)(n >> 16), (uint8_t)(n >> 8), (uint8_t)n,
                    (uint8_t)(range >> 24), (uint8_t)(range >> 16), (uint8_t)(range >> 8), (uint8_t)range};
    memcpy(out, h, 8); memcpy(out + 8, packet, (size_t)n); return 8 + (size_t)n;
}
static void tone(int16_t *pcm, int channels, int index) {
    for (int i = 0; i < FRAME; i++) for (int c = 0; c < channels; c++)
        pcm[i * channels + c] = (int16_t)(8000 * sin(2 * PI * (440 + 110 * c) * (index * FRAME + i) / RATE));
}
static double rms(const int16_t *pcm, int n) { double s = 0; for (int i = 0; i < n; i++) s += (double)pcm[i] * pcm[i]; return sqrt(s / n); }
static int decode_all(uint32_t dec, int channels, uint32_t cmd, int multistream, int *energy_ok) {
    int ok = 1; *energy_ok = 1;
    int err; OpusEncoder *single = NULL; OpusMSEncoder *multi = NULL;
    unsigned char mapping[4] = {0, 1, 2, 3};
    if (multistream) multi = opus_multistream_encoder_create(RATE, channels, 2, 2, mapping, OPUS_APPLICATION_AUDIO, &err);
    else single = opus_encoder_create(RATE, channels, OPUS_APPLICATION_AUDIO, &err);
    if (err != OPUS_OK) runtime_fail("test opus encoder");
    uint8_t *in = low(4096); int16_t *out = low(sizeof(int16_t) * FRAME * channels);
    int16_t pcm[FRAME * 4]; uint8_t packet[1500];
    for (int f = 0; f < FRAMES; f++) {
        tone(pcm, channels, f);
        int n = multi ? opus_multistream_encode(multi, pcm, FRAME, packet, sizeof packet) : opus_encode(single, pcm, FRAME, packet, sizeof packet);
        opus_uint32 range = 0;
        if (multi) opus_multistream_encoder_ctl(multi, OPUS_GET_FINAL_RANGE(&range)); else opus_encoder_ctl(single, OPUS_GET_FINAL_RANGE(&range));
        size_t size = frame(in, packet, n, range);
        uint8_t reset = f == 0;
        Reply r = call(dec, cmd, &reset, cmd >= 6 ? 1 : 0, &(Extra){.a = {in, size}, .b = {out, sizeof(int16_t) * FRAME * channels}});
        ok &= !r.result && u32_at(&r, 0) == size && u32_at(&r, 4) == FRAME;
        if (f >= 4) *energy_ok &= fabs(rms(out, FRAME * channels) - rms(pcm, FRAME * channels)) < 0.35 * rms(pcm, FRAME * channels);
    }
    if (multi) opus_multistream_encoder_destroy(multi); else opus_encoder_destroy(single);
    return ok;
}
static void hwopus(void) {
    uint32_t m = open_service("hwopus");
    int32_t fmt[2] = {RATE, 2};
    Reply r = call(m, 1, fmt, 8, NULL);
    uint32_t size = u32_at(&r, 0);
    CHECK(!r.result && size > 0x1000, "hwopus GetWorkBufferSize(48000, 2) = %#x", size);
    uint32_t tmem = runtime_handle_new(0, NULL);
    struct { int32_t rate, channels; uint32_t size; } open = {RATE, 2, size};
    uint32_t dec = object(m, 0, &open, sizeof open, &(Extra){.copy = tmem});
    int energy;
    CHECK(decode_all(dec, 2, 8, 0, &energy), "hwopus DecodeInterleaved (cmd 8): %d frames, 8 + payload consumed, %d samples each", FRAMES, FRAME);
    CHECK(energy, "hwopus: the decoded tone has the encoded tone's level");
    CHECK(decode_all(dec, 2, 0, 0, &energy) && energy, "hwopus DecodeInterleavedOld (cmd 0)");
    uint8_t *bad = low(16); bad[3] = 200; int16_t *out = low(4096);
    r = call(dec, 0, NULL, 0, &(Extra){.a = {bad, 16}, .b = {out, 4096}});
    CHECK(r.result == 0x46f, "hwopus: a frame longer than its buffer = 2111-0002");
    int32_t wrong[2] = {44100, 2};
    r = call(m, 1, wrong, 8, NULL);
    CHECK(!r.result && u32_at(&r, 0) == 0, "hwopus GetWorkBufferSize(44100 Hz) = 0 (not an Opus rate)");
    struct { int32_t rate, channels; uint32_t size; } open_wrong = {44100, 2, size};
    CHECK(call(m, 0, &open_wrong, sizeof open_wrong, &(Extra){.copy = tmem}).result == 0x26f, "hwopus open at 44100 Hz = 2111-0001");

    /* Multistream (Ex): 4 channels in 2 coupled streams. */
    uint8_t *params = low(0x118);
    int32_t head[6] = {RATE, 4, 2, 2, 0, 0}; memcpy(params, head, sizeof head);
    for (int i = 0; i < 4; i++) params[0x18 + i] = (uint8_t)i;
    r = call(m, 7, NULL, 0, &(Extra){.x = {params, 0x118}});
    uint32_t msize = u32_at(&r, 0);
    CHECK(!r.result && msize > 0x1000, "hwopus GetWorkBufferSizeForMultiStreamEx(4 channels, 2 coupled streams) = %#x", msize);
    uint32_t mdec = object(m, 6, &msize, 4, &(Extra){.x = {params, 0x118}, .copy = tmem});
    CHECK(decode_all(mdec, 4, 9, 1, &energy) && energy, "hwopus DecodeInterleavedForMultiStream (cmd 9): 4 channels decoded");
}
static void hwopus_range(void) {
    uint32_t m = open_service("hwopus");
    int32_t fmt[2] = {RATE, 1};
    Reply r = call(m, 1, fmt, 8, NULL);
    uint32_t size = u32_at(&r, 0);
    struct { int32_t rate, channels; uint32_t size; } open = {RATE, 1, size};
    uint32_t dec = object(m, 0, &open, sizeof open, &(Extra){.copy = runtime_handle_new(0, NULL)});
    int err; OpusEncoder *e = opus_encoder_create(RATE, 1, OPUS_APPLICATION_AUDIO, &err);
    int16_t pcm[FRAME]; tone(pcm, 1, 0); uint8_t packet[1500];
    int n = opus_encode(e, pcm, FRAME, packet, sizeof packet);
    opus_uint32 range = 0; opus_encoder_ctl(e, OPUS_GET_FINAL_RANGE(&range));
    uint8_t *in = low(2048); int16_t *out = low(sizeof pcm);
    size_t fs = frame(in, packet, n, range ^ 1);
    call(dec, 0, NULL, 0, &(Extra){.a = {in, fs}, .b = {out, sizeof pcm}});
    puts("unexpected: a wrong final range was accepted");
}

int main(int argc, char **argv) {
    if (argc < 2) return 2;
    if (pthread_key_create(&runtime_keys[2], NULL) || pthread_setspecific(runtime_keys[2], msg)) return 2;
    if (!strcmp(argv[1], "all")) {
        aoc(); pctl(); ldn(); shop(); applets(); hwopus();
        printf("%s: %d failed\n", failures ? "FAIL" : "ok", failures);
        return failures != 0;
    }
    if (!strcmp(argv[1], "command") && argc == 4) {
        call(open_service(argv[2]), (uint32_t)strtoul(argv[3], NULL, 0), NULL, 0, NULL);
        puts("unexpected: command answered"); return 1;
    }
    if (!strcmp(argv[1], "ldn-command") && argc == 3) {
        uint32_t comm = object(open_service("ldn:u"), 0, NULL, 0, NULL);
        call(comm, (uint32_t)strtoul(argv[2], NULL, 0), NULL, 0, NULL);
        puts("unexpected: command answered"); return 1;
    }
    if (!strcmp(argv[1], "hwopus-range")) { hwopus_range(); return 1; }
    return 2;
}
