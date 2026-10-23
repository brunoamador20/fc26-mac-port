/* IPC test for audin:u (ListAudioIns returns 0 devices) */
#include "runtime.h"
#include "ipc.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>

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
uint32_t runtime_event_new(void) { return 1; }
uint32_t runtime_event_readable(uint32_t e) { return e; }
void runtime_event_signal(uint32_t e) { (void)e; }

static uint32_t msg[64] __attribute__((aligned(16)));
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

int main(void) {
    if (pthread_key_create(&runtime_keys[2], NULL) || pthread_setspecific(runtime_keys[2], msg)) return 2;
    uint32_t sm = connect_port("sm:");
    request(0, NULL, 0); sync_request(sm);

    uint32_t audin = open_service(sm, "audin:u");
    assert(audin != 0);

    /* Command 0: ListAudioIns -> should return count = 0 */
    request(0, NULL, 0);
    sync_request(audin);
    const uint8_t *data;
    uint32_t res = reply_result(&data);
    assert(res == 0);
    uint32_t count = 0;
    memcpy(&count, data, 4);
    assert(count == 0);

    /* Command 2: ListAudioInsAuto -> should also return count = 0 */
    request(2, NULL, 0);
    sync_request(audin);
    res = reply_result(&data);
    assert(res == 0);
    count = 0;
    memcpy(&count, data, 4);
    assert(count == 0);

    /* Command 1: OpenAudioIn -> must fail with 0x299 (DeviceNotFound) */
    request(1, NULL, 0);
    sync_request(audin);
    res = reply_result(&data);
    assert(res == 0x299);

    /* Command 3: OpenAudioInAuto -> must fail with 0x299 (DeviceNotFound) */
    request(3, NULL, 0);
    sync_request(audin);
    res = reply_result(&data);
    assert(res == 0x299);

    /* Command 5: OpenAudioInProtocolSpecified -> must fail with 0x299 (DeviceNotFound) */
    request(5, NULL, 0);
    sync_request(audin);
    res = reply_result(&data);
    assert(res == 0x299);

    /* Command 4: AcquireAudioDeviceNotificationForInput -> must return a readable handle */
    request(4, NULL, 0);
    sync_request(audin);
    res = reply_result(&data);
    assert(res == 0);
    assert(msg[1] >> 31); /* special flag (handle returned) */
    assert(msg[3] != 0);  /* event handle */

    printf("AUDIN_IPC_OK\n");
    return 0;
}
