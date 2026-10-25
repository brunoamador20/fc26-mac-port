/* FC 26 without the EA servers, without the game: the host's network answers (runtime/system_services.c,
   offline_applets.c) never leave the game waiting. bsd:u requests are built as the SDK's CMIF client builds them and
   sent through the same SVC entry the rewritten code reaches (SendSyncRequest on the thread's message buffer); the
   functions answered by name are taken from runtime_game_override / runtime_offline_applet_override, as the loader
   takes them, and called. Stops go through the runtime's own runtime_fail / runtime_missing (missing.c).
   Usage: offline_net_test bsd | names | command <id>
     bsd       every descriptor command fails at once (connect, recv, send, ... EBADF; socket ENETDOWN); exit 0
     names     nifm, socket::GetAddrInfo and nn::friends answer as a console without a network; exit 0
     command   a bsd:u command the host does not know still stops with its name and number (exit 1) */
#include "runtime.h"
#include "ipc.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

pthread_key_t runtime_keys[8];
uint64_t runtime_now_ns(void) { return 0; } /* profiler disabled in this IPC fixture */
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
void dm_guest_write_prepare(void *addr, size_t n) { (void)addr; (void)n; }
void *runtime_offline_applet_override(const char *name);

static int failures;
#define CHECK(cond, ...) do { if (cond) { printf("ok: "); printf(__VA_ARGS__); putchar('\n'); } \
                              else { printf("FAIL: "); printf(__VA_ARGS__); printf("  (%s, line %d)\n", #cond, __LINE__); failures++; } } while (0)

static uint32_t msg[64] __attribute__((aligned(16)));
/* HIPC header (type 4: CMIF request; data words), padding to the 16-byte boundary, the CMIF header, the arguments. */
static void request(uint32_t cmd, const void *args, unsigned n) {
    memset(msg, 0, sizeof msg);
    msg[0] = 4; msg[1] = (8 + 16 + n + 16 + 3) / 4;
    uint32_t h[4] = {0x49434653u, 0, cmd, 0};
    memcpy((uint8_t *)msg + 16, h, 16);
    if (n) memcpy((uint8_t *)msg + 32, args, n);
}
static void sync_request(uint32_t handle) {
    uint64_t r[31] = {0}; r[0] = handle;
    if (!runtime_ipc_svc(0x21, r) || r[0]) { fprintf(stderr, "SendSyncRequest %#x: %#llx\n", handle, (unsigned long long)r[0]); exit(1); }
}
/* The reply's CMIF result, its data and the data size: the HIPC data words less the padding, the CMIF header and the
   16 bytes of alignment slack runtime/ipc.c keeps after the data, as libnx does. */
static uint32_t reply(const uint8_t **data, unsigned *size) {
    unsigned special = msg[1] >> 31, words = 2 + (special ? 1 + ((msg[2] >> 1) & 15) + ((msg[2] >> 5) & 15) : 0);
    const uint8_t *payload = (const uint8_t *)msg + ((words * 4 + 15) & ~15u);
    uint32_t h[4]; memcpy(h, payload, 16);
    if (h[0] != 0x4f434653u) { fprintf(stderr, "reply magic %#x\n", h[0]); exit(1); }
    if (data) *data = payload + 16;
    if (size) {
        unsigned total = (msg[1] & 0x3ff) * 4, pad = (unsigned)(payload - (const uint8_t *)msg) - words * 4;
        *size = total - pad - 32;
    }
    return h[2];
}
static uint32_t connect_port(const char *name) {
    char port[16] = {0}; memcpy(port, name, strnlen(name, 12));
    uint64_t r[31] = {0}; r[1] = (uintptr_t)port;
    if (!runtime_ipc_svc(0x1f, r) || r[0]) { fprintf(stderr, "ConnectToNamedPort %s\n", name); exit(1); }
    return (uint32_t)r[1];
}
static uint32_t open_service(uint32_t sm, const char *name) {
    char n[8] = {0}; memcpy(n, name, strnlen(name, 8));
    request(1, n, 8); sync_request(sm);
    if (reply(NULL, NULL) || !(msg[1] >> 31)) { fprintf(stderr, "GetServiceHandle %s: no handle\n", name); exit(1); }
    return msg[3];
}
static double now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return (double)t.tv_sec + t.tv_nsec / 1e9; }

/* One bsd:u command with a descriptor (and the other u32 arguments libnx sends); its {ret, errno[, length]}. */
static void bsd_call(uint32_t bsd, uint32_t cmd, int32_t *ret, uint32_t *err, int *has_length, uint32_t *length) {
    uint32_t args[4] = {7, 0, 0, 0};   /* fd 7: a descriptor the game could hold if a socket had ever been made */
    request(cmd, args, sizeof args); sync_request(bsd);
    const uint8_t *data; unsigned size; uint32_t result = reply(&data, &size);
    if (result) { printf("FAIL: bsd cmd %u result %#x\n", cmd, result); failures++; }
    memcpy(ret, data, 4); memcpy(err, data + 4, 4);
    *has_length = size >= 12; *length = 0;
    if (*has_length) memcpy(length, data + 8, 4);
}

static int bsd_case(uint32_t sm) {
    uint32_t bsd = open_service(sm, "bsd:u");
    request(0, NULL, 0); sync_request(bsd); CHECK(reply(NULL, NULL) == 0, "bsd:u RegisterClient");
    uint32_t socket_args[3] = {2, 1, 6};   /* AF_INET, SOCK_STREAM, IPPROTO_TCP: a connection to an EA server */
    request(2, socket_args, sizeof socket_args); sync_request(bsd);
    const uint8_t *data; reply(&data, NULL);
    int32_t ret; uint32_t err; memcpy(&ret, data, 4); memcpy(&err, data + 4, 4);
    CHECK(ret == -1 && err == 50, "bsd:u Socket = -1, ENETDOWN (ret %d errno %u)", ret, err);
    static const struct { uint32_t cmd; const char *name; int length; } fd_commands[] = {
        {8, "Recv", 0}, {9, "RecvFrom", 1}, {10, "Send", 0}, {11, "SendTo", 0}, {12, "Accept", 1}, {13, "Bind", 0},
        {14, "Connect", 0}, {15, "GetPeerName", 1}, {16, "GetSockName", 1}, {17, "GetSockOpt", 1}, {18, "Listen", 0},
        {19, "Ioctl", 0}, {20, "Fcntl", 0}, {21, "SetSockOpt", 0}, {22, "Shutdown", 0}, {24, "Write", 0}, {25, "Read", 0},
        {26, "Close", 0}, {27, "DuplicateSocket", 0},
    };
    for (size_t i = 0; i < sizeof fd_commands / sizeof *fd_commands; i++) {
        int has_length; uint32_t length;
        double t0 = now();
        bsd_call(bsd, fd_commands[i].cmd, &ret, &err, &has_length, &length);
        double ms = (now() - t0) * 1000;
        CHECK(ret == -1 && err == 9 && has_length == fd_commands[i].length && length == 0 && ms < 100,
              "bsd:u %s (%u) = -1, EBADF at once (ret %d errno %u, length field %d, %.3f ms)", fd_commands[i].name,
              fd_commands[i].cmd, ret, err, has_length, ms);
    }
    request(23, (uint32_t[]){2}, 4); sync_request(bsd); reply(&data, NULL);
    memcpy(&ret, data, 4); memcpy(&err, data + 4, 4);
    CHECK(ret == 0 && err == 0, "bsd:u ShutdownAllSockets = 0 (there are none)");
    printf("ok: %d failed\n", failures);
    return failures != 0;
}

typedef uint32_t (*Fn0)(void);
static void *need(const char *name) {
    void *f = runtime_game_override(name);
    if (!f) { printf("FAIL: %s is not answered by name\n", name); failures++; }
    return f;
}
static int names_case(void) {
    /* nifm: no network, no request on hold, nothing to retry. */
    uint8_t (*available)(void) = need("_ZN2nn4nifm18IsNetworkAvailableEv");
    uint8_t (*on_hold)(void) = need("_ZN2nn4nifm22IsNetworkRequestOnHoldEv");
    uint8_t (*retry)(void) = need("_ZN2nn4nifm31HandleNetworkRequestErrorResultEv");
    if (available && on_hold && retry) {
        uint8_t a = available(), h = on_hold(), r = retry();
        CHECK(a == 0 && h == 0 && r == 0, "nifm IsNetworkAvailable false, IsNetworkRequestOnHold false, "
              "HandleNetworkRequestErrorResult false (bool, no retry) (%u %u %u)", a, h, r);
    }
    uint32_t (*ip)(uint8_t *) = need("_ZN2nn4nifm26GetCurrentPrimaryIpAddressEPNS_6socket6InAddrE");
    if (ip) {
        uint8_t addr[4] = {1, 2, 3, 4}; uint32_t result = ip(addr);
        CHECK(result != 0 && !memcmp(addr, "\0\0\0\0", 4), "nifm GetCurrentPrimaryIpAddress(nn::socket::InAddr*) fails, address 0.0.0.0 (%#x)", result);
    }
    /* GetAddrInfo: at once, EAI_AGAIN, no list. */
    int32_t (*gai)(const char *, const char *, const void *, void **) = need("_ZN2nn6socket11GetAddrInfoEPKcS2_PKNS0_8AddrInfoEPPS3_");
    void (*freeai)(void *) = need("_ZN2nn6socket12FreeAddrInfoEPNS0_8AddrInfoE");
    if (gai && freeai) {
        void *res = (void *)1; double t0 = now();
        int32_t r = gai("spring18.gosredirector.ea.com", "42230", NULL, &res);
        double ms = (now() - t0) * 1000;
        CHECK(r == 2 && res == NULL && ms < 100, "nn::socket::GetAddrInfo(EA redirector) = EAI_AGAIN, no list, %.3f ms", ms);
        freeai(res);
        CHECK(1, "nn::socket::FreeAddrInfo(NULL) returns");
    }
    /* friends: empty local lists, server requests fail before any AsyncContext starts, no notification. */
    static const char *const lists[] = {
        "_ZN2nn7friends13GetFriendListEPiPNS0_6FriendERKNS_7account3UidEiiRKNS0_12FriendFilterE",
        "_ZN2nn7friends13GetFriendListEPiPNS_7account23NetworkServiceAccountIdERKNS2_3UidEiiRKNS0_12FriendFilterE",
        "_ZN2nn7friends18GetBlockedUserListEPiPNS_7account23NetworkServiceAccountIdERKNS2_3UidEii"};
    for (size_t i = 0; i < 3; i++) {
        uint32_t (*list)(int32_t *) = need(lists[i]);
        if (!list) continue;
        int32_t count = 99; uint32_t result = list(&count);
        CHECK(result == 0 && count == 0, "%s = 0, 0 entries", lists[i]);
    }
    static const char *const fail[] = {
        "_ZN2nn7friends25EnsureFriendListAvailableEPNS0_12AsyncContextERKNS_7account3UidE",
        "_ZN2nn7friends30EnsureBlockedUserListAvailableEPNS0_12AsyncContextERKNS_7account3UidE",
        "_ZN2nn7friends14GetProfileListEPNS0_12AsyncContextEPNS0_7ProfileERKNS_7account3UidEPKNS5_23NetworkServiceAccountIdEi",
        "_ZN2nn7friends17NotificationQueue3PopEPNS0_16NotificationInfoE"};
    for (size_t i = 0; i < 4; i++) {
        Fn0 f = need(fail[i]);
        if (f) { uint32_t r = f(); CHECK(r != 0 && (r & 0x1ff) == 121, "%s fails at once (friends result %#x)", fail[i], r); }
    }
    static const char *const fine[] = {
        "_ZN2nn7friends10InitializeEv", "_ZN2nn7friends12UserPresence10InitializeEv",
        "_ZN2nn7friends12UserPresence14SetDescriptionEPKc", "_ZN2nn7friends12UserPresence6CommitEv",
        "_ZN2nn7friends16UpdateFriendInfoEPNS0_6FriendERKNS_7account3UidEPKNS3_23NetworkServiceAccountIdEi",
        "_ZN2nn7friends17NotificationQueue10InitializeERKNS_7account3UidE", "_ZN2nn7friends17NotificationQueue8FinalizeEv",
        "_ZN2nn7friends28DeclareOpenOnlinePlaySessionEv", "_ZN2nn7friends29DeclareCloseOnlinePlaySessionEv"};
    for (size_t i = 0; i < 9; i++) { Fn0 f = need(fine[i]); if (f) { f(); CHECK(1, "%s answered by the host", fine[i]); } }
    static const char *const applets[] = {"_ZN2nn7friends14ShowFriendListERKNS_7account3UidE",
        "_ZN2nn7friends18ShowUserDetailInfoERKNS_7account3UidERKNS1_23NetworkServiceAccountIdERKNS0_15InAppScreenNameESA_"};
    for (size_t i = 0; i < 2; i++) {
        Fn0 f = runtime_offline_applet_override(applets[i]);
        CHECK(f && f() == 0, "%s: closed at once, Result 0", applets[i]);
    }
    printf("ok: %d failed\n", failures);
    return failures != 0;
}

int main(int argc, char **argv) {
    if (argc < 2) return 2;
    if (pthread_key_create(&runtime_keys[2], NULL) || pthread_setspecific(runtime_keys[2], msg)) return 2;
    if (!strcmp(argv[1], "names")) return names_case();
    uint32_t sm = connect_port("sm:");
    request(0, NULL, 0); sync_request(sm);                                       /* RegisterClient */
    if (!strcmp(argv[1], "bsd")) return bsd_case(sm);
    if (!strcmp(argv[1], "command") && argc == 3) {
        uint32_t bsd = open_service(sm, "bsd:u");
        uint32_t args[4] = {7, 0, 0, 0};
        request((uint32_t)strtoul(argv[2], NULL, 0), args, sizeof args); sync_request(bsd);
        puts("unexpected: command answered"); return 1;
    }
    return 2;
}
