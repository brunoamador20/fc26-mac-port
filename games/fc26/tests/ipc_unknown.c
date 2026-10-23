/* Unknown IPC services, commands and named ports stop the runtime with their name and number (runtime/ipc.c), without
   the game: requests are built as the SDK's CMIF client builds them and sent through the same SVC entry the rewritten
   code reaches (SendSyncRequest on the thread's message buffer). The registered services are system_services.c's
   (set, bsd:u). Usage: ipc_unknown open | service <name> | tipc-service <name> | command <service> <id> | port <name>.
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
_Noreturn void runtime_fail(const char *message) { fprintf(stderr, "[totk] FAIL: %s\n", message); exit(3); }
void runtime_trace_guest(uint64_t fp, uint64_t lr) { (void)fp; (void)lr; }
uint64_t runtime_desired_language(void) { uint64_t v = 0; memcpy(&v, "en-US", 5); return v; }

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
    if (!strcmp(argv[1], "service") && argc == 3) { open_service(sm, argv[2]); puts("unexpected: service opened"); return 1; }
    if (!strcmp(argv[1], "tipc-service") && argc == 3) {
        memset(msg, 0, sizeof msg); msg[0] = 16 + 1; msg[1] = 2;            /* TIPC GetServiceHandle(name) */
        memcpy(&msg[2], argv[2], strnlen(argv[2], 8));
        sync_request(sm); puts("unexpected: service opened"); return 1;
    }
    if (!strcmp(argv[1], "command") && argc == 4) {
        uint32_t s = open_service(sm, argv[2]);
        request((uint32_t)strtoul(argv[3], NULL, 0), NULL, 0); sync_request(s);
        puts("unexpected: command answered"); return 1;
    }
    return 2;
}
