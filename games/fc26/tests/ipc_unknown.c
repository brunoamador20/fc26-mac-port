/* Unknown IPC services, commands and named ports stop the runtime with their name and number (runtime/ipc.c), without
   the game: requests are built as the SDK's CMIF client builds them and sent through the same SVC entry the rewritten
   code reaches (SendSyncRequest on the thread's message buffer). The registered services are system_services.c's
   (set, bsd:u); stops go through the runtime's own runtime_fail / runtime_missing (missing.c).
   Usage: ipc_unknown open | service <name> | tipc-service <name> | command <service> <id> | port <name> | message-type <n> | fail <message> | svc <num> | svc-test.
   tipc-service asks sm: in the TIPC framing newer SDKs use for it (type 16 + command, arguments right after the header). */
#include "runtime.h"
#include "ipc.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

pthread_key_t runtime_keys[8];
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
uint64_t runtime_svc(unsigned num, uint64_t *r, const char *module, uint64_t offset) {
    if (runtime_ipc_svc(num, r)) return r[0];
    fprintf(stderr, "[totk] unimplemented SVC 0x%x at %s+%#llx\n", num, module, (unsigned long long)offset);
    runtime_missing("svc: number 0x%x at %s+%#llx", num, module, (unsigned long long)offset);
    runtime_fail("system service not implemented");
    return 0;
}

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
/* The reply's CMIF result and, after it, its data; a moved handle sits in the special header (word 3). */
static uint32_t reply_result(const uint8_t **data) {
    unsigned special = msg[1] >> 31, words = 2 + (special ? 1 + ((msg[2] >> 1) & 15) + ((msg[2] >> 5) & 15) : 0);
    const uint8_t *payload = (const uint8_t *)msg + ((words * 4 + 15) & ~15u);
    uint32_t h[4]; memcpy(h, payload, 16);
    if (h[0] != 0x4f434653u) { fprintf(stderr, "reply magic %#x\n", h[0]); exit(1); }
    if (data) *data = payload + 16;
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
    if (reply_result(NULL) || !(msg[1] >> 31)) { fprintf(stderr, "GetServiceHandle %s: no handle\n", name); exit(1); }
    return msg[3];
}

int main(int argc, char **argv) {
    if (argc < 2) return 2;
    if (pthread_key_create(&runtime_keys[2], NULL) || pthread_setspecific(runtime_keys[2], msg)) return 2;
    if (!strcmp(argv[1], "fail") && argc == 3) runtime_fail(argv[2]);   /* runtime_fail alone, no runtime_missing first */
    if (!strcmp(argv[1], "port") && argc == 3) { connect_port(argv[2]); puts("unexpected: port opened"); return 1; }
    uint32_t sm = connect_port("sm:");
    request(0, NULL, 0); sync_request(sm);                                       /* RegisterClient */
    if (!strcmp(argv[1], "open")) {
        uint32_t set = open_service(sm, "set");
        request(0, NULL, 0); sync_request(set);                                  /* GetLanguageCode */
        const uint8_t *data; uint32_t result = reply_result(&data);
        char code[9] = {0}; memcpy(code, data, 8);
        printf("ipc ok: set opened, GetLanguageCode result %u code %s\n", result, code);
        return result || strcmp(code, "en-US");
    }
    if (!strcmp(argv[1], "bsd-cmd") && argc == 3) {
        uint32_t bsd = open_service(sm, "bsd:u");
        uint32_t cmd = (uint32_t)strtoul(argv[2], NULL, 0);
        request(cmd, NULL, 0); sync_request(bsd);
        const uint8_t *data; uint32_t result = reply_result(&data);
        if (result) { printf("bsd cmd %u failed with result %#x\n", cmd, result); return 1; }
        int32_t ret; uint32_t err;
        memcpy(&ret, data, 4); memcpy(&err, data + 4, 4);
        printf("bsd cmd %u: ret %d err %u\n", cmd, ret, err);
        return 0;
    }
    if (!strcmp(argv[1], "time-open")) {
        uint32_t time_s = open_service(sm, "time:u");
        request(3, NULL, 0); sync_request(time_s);                              /* GetTimeZoneService */
        if (reply_result(NULL) || !(msg[1] >> 31)) { fprintf(stderr, "GetTimeZoneService failed\n"); return 1; }
        uint32_t tz = msg[3];
        request(0, NULL, 0); sync_request(tz);                                   /* GetDeviceLocationName */
        const uint8_t *data; uint32_t result = reply_result(&data);
        char loc[0x25] = {0}; memcpy(loc, data, 0x24);
        printf("time ok: timezone location %s result %u\n", loc, result);
        return result || !loc[0];
    }
    if (!strcmp(argv[1], "svc") && argc == 3) {
        unsigned num = (unsigned)strtoul(argv[2], NULL, 0);
        uint64_t r[31] = {0};
        runtime_svc(num, r, "main", 0x1234);
        puts("unexpected: svc answered");
        return 1;
    }
    if (!strcmp(argv[1], "svc-test")) {
        uint64_t r[31] = {0};
        /* 0x15: CreateTransferMemory */
        r[1] = 0x10000; r[2] = 0x2000; r[3] = 0;
        if (!runtime_ipc_svc(0x15, r) || r[0] != 0) { fprintf(stderr, "svc 0x15 failed\n"); return 1; }

        /* 0x23: SendAsyncRequestWithUserBuffer */
        uint32_t set_svc = open_service(sm, "set");
        uint32_t req_msg[64] = {0};
        req_msg[0] = 4; req_msg[1] = (8 + 16 + 16 + 3) / 4;
        uint32_t h[4] = {0x49434653u, 0, 0, 0};
        memcpy((uint8_t *)req_msg + 16, h, 16);
        memset(r, 0, sizeof r);
        r[1] = (uintptr_t)req_msg; r[2] = sizeof req_msg; r[3] = set_svc;
        if (!runtime_ipc_svc(0x23, r) || r[0] != 0 || !r[1]) { fprintf(stderr, "svc 0x23 failed\n"); return 1; }

        /* As 8 SVCs removidas caem no caminho de não implementada (runtime_ipc_svc retorna 0) */
        static const unsigned removed_svcs[] = {0x13, 0x14, 0x50, 0x51, 0x52, 0x4b, 0x40, 0x41};
        for (size_t i = 0; i < sizeof removed_svcs / sizeof removed_svcs[0]; i++) {
            memset(r, 0, sizeof r);
            if (runtime_ipc_svc(removed_svcs[i], r) != 0) {
                fprintf(stderr, "svc %#x unexpectedly handled by ipc\n", removed_svcs[i]);
                return 1;
            }
        }

        printf("svc test ok\n");
        return 0;
    }
    if (!strcmp(argv[1], "service") && argc == 3) { open_service(sm, argv[2]); puts("unexpected: service opened"); return 1; }
    if (!strcmp(argv[1], "tipc-service") && argc == 3) {
        memset(msg, 0, sizeof msg); msg[0] = 16 + 1; msg[1] = 2;            /* TIPC GetServiceHandle(name) */
        memcpy(&msg[2], argv[2], strnlen(argv[2], 8));
        sync_request(sm); puts("unexpected: service opened"); return 1;
    }
    if (!strcmp(argv[1], "message-type") && argc == 3) {                /* a HIPC type the host does not know */
        uint32_t set = open_service(sm, "set");
        request(0, NULL, 0); msg[0] = (uint32_t)strtoul(argv[2], NULL, 0); sync_request(set);
        puts("unexpected: message answered"); return 1;
    }
    if (!strcmp(argv[1], "command") && argc == 4) {
        uint32_t s = open_service(sm, argv[2]);
        request((uint32_t)strtoul(argv[3], NULL, 0), NULL, 0); sync_request(s);
        puts("unexpected: command answered"); return 1;
    }
    return 2;
}
