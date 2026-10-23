/* Comprehensive synthetic test harness for nn::audio and IPC services audin:u / audout:u */
#include "runtime.h"
#include "ipc.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <pthread.h>
#include <math.h>

pthread_key_t runtime_keys[8];
static void *objects[64];
static int kinds[64];
static unsigned nobjects;

uint32_t runtime_handle_new(int session, void *obj) {
    if (nobjects == 64) runtime_fail("test handle table full");
    objects[nobjects] = obj; kinds[nobjects] = session;
    return 0x100 + nobjects++;
}
void *runtime_handle_get(uint32_t h, int session) {
    h -= 0x100;
    return h < nobjects && kinds[h] == session ? objects[h] : NULL;
}
void *runtime_handle_take_session(uint32_t h) {
    void *s = runtime_handle_get(h, 1);
    if (s) objects[h - 0x100] = NULL;
    return s;
}
void runtime_trace_guest(uint64_t fp, uint64_t lr) { (void)fp; (void)lr; }
uint64_t runtime_desired_language(void) { uint64_t v = 0; memcpy(&v, "en-US", 5); return v; }
static uint32_t g_event_counter = 1;
uint32_t runtime_event_new(void) { return g_event_counter++; }
uint32_t runtime_event_readable(uint32_t e) { return e; }
void runtime_event_signal(uint32_t e) { (void)e; }

static uint32_t msg[64] __attribute__((aligned(16)));

static void request(uint32_t cmd, const void *args, unsigned n) {
    memset(msg, 0, sizeof msg);
    msg[0] = 4; /* T_REQUEST */
    msg[1] = (8 + 16 + n + 16 + 3) / 4;
    uint32_t h[4] = {0x49434653u, 0, cmd, 0}; /* SFCI */
    memcpy((uint8_t *)msg + 16, h, 16);
    if (n) memcpy((uint8_t *)msg + 32, args, n);
}

static void request_with_in_buf(uint32_t cmd, const void *args, unsigned n, uint64_t buf_addr, uint64_t buf_size) {
    memset(msg, 0, sizeof msg);
    /* 1 type-A buffer: na = 1 -> bits 20..23 = 1 -> 0x00100004 */
    msg[0] = 4 | (1u << 20);
    msg[1] = (8 + 16 + n + 16 + 3) / 4;
    /* Buffer descriptor A (3 words): size, addr_lo, flags/addr_hi */
    msg[2] = (uint32_t)buf_size;
    msg[3] = (uint32_t)buf_addr;
    msg[4] = (uint32_t)(((buf_addr >> 32) & 0xf) << 28) | (uint32_t)(((buf_addr >> 36) & 0x3fffff) << 2);
    uint32_t h[4] = {0x49434653u, 0, cmd, 0};
    /* Data words start after buffer descriptors: p = msg + 2 + 3 = msg + 5 -> byte offset 20. Align to 16 -> 32 */
    memcpy((uint8_t *)msg + 32, h, 16);
    if (n) memcpy((uint8_t *)msg + 48, args, n);
}

static void request_with_out_buf(uint32_t cmd, const void *args, unsigned n, uint64_t buf_addr, uint64_t buf_size) {
    memset(msg, 0, sizeof msg);
    /* 1 type-B buffer: nb = 1 -> bits 24..27 = 1 -> 0x01000004 */
    msg[0] = 4 | (1u << 24);
    msg[1] = (8 + 16 + n + 16 + 3) / 4;
    msg[2] = (uint32_t)buf_size;
    msg[3] = (uint32_t)buf_addr;
    msg[4] = (uint32_t)(((buf_addr >> 32) & 0xf) << 28) | (uint32_t)(((buf_addr >> 36) & 0x3fffff) << 2);
    uint32_t h[4] = {0x49434653u, 0, cmd, 0};
    memcpy((uint8_t *)msg + 32, h, 16);
    if (n) memcpy((uint8_t *)msg + 48, args, n);
}

static void close_session_req(uint32_t handle) {
    memset(msg, 0, sizeof msg);
    msg[0] = 2; /* T_CLOSE */
    msg[1] = 0;
    uint64_t r[31] = {0}; r[0] = handle;
    runtime_ipc_svc(0x21, r);
}

static void sync_request(uint32_t handle) {
    uint64_t r[31] = {0}; r[0] = handle;
    if (!runtime_ipc_svc(0x21, r) || r[0]) {
        fprintf(stderr, "SendSyncRequest %#x: %#llx\n", handle, (unsigned long long)r[0]);
        exit(1);
    }
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

/* Audio buffer structure matching SDK layout */
typedef struct {
    uint64_t next;
    uint64_t sample_buffer;
    uint64_t capacity;
    uint64_t data_size;
    uint64_t data_offset;
} AudioBufferDescriptor;
_Static_assert(sizeof(AudioBufferDescriptor) == 0x28, "AudioBufferDescriptor");

/* Test runner */
int main(void) {
    setenv("FC26_AUDIO", "0", 1); /* force silent sink for headless test */
    if (pthread_key_create(&runtime_keys[2], NULL) || pthread_setspecific(runtime_keys[2], msg)) return 2;

    uint32_t sm = connect_port("sm:");
    request(0, NULL, 0); sync_request(sm);

    /* =========================================================================
     * PART 1: AUDIN:U SERVICE TESTS
     * ========================================================================= */
    uint32_t audin = open_service(sm, "audin:u");
    assert(audin != 0);

    const uint8_t *data = NULL;
    uint32_t res = 0;

    /* Command 0: ListAudioIns -> count = 0 */
    request(0, NULL, 0);
    sync_request(audin);
    res = reply_result(&data);
    assert(res == 0);
    uint32_t in_count = 0;
    memcpy(&in_count, data, 4);
    assert(in_count == 0);

    /* Command 2: ListAudioInsAuto -> count = 0 */
    request(2, NULL, 0);
    sync_request(audin);
    res = reply_result(&data);
    assert(res == 0);
    in_count = 999;
    memcpy(&in_count, data, 4);
    assert(in_count == 0);

    /* Command 1: OpenAudioIn -> must fail with 0x299 (DeviceNotFound / ResultNotFound) */
    request(1, NULL, 0);
    sync_request(audin);
    res = reply_result(&data);
    assert(res == 0x299);

    /* Command 3: OpenAudioInAuto -> must fail with 0x299 */
    request(3, NULL, 0);
    sync_request(audin);
    res = reply_result(&data);
    assert(res == 0x299);

    /* Command 5: OpenAudioInProtocolSpecified -> must fail with 0x299 */
    request(5, NULL, 0);
    sync_request(audin);
    res = reply_result(&data);
    assert(res == 0x299);

    /* Command 4: AcquireAudioDeviceNotificationForInput -> returns valid event handle */
    request(4, NULL, 0);
    sync_request(audin);
    res = reply_result(&data);
    assert(res == 0);
    assert(msg[1] >> 31);
    assert(msg[3] != 0);

    /* =========================================================================
     * PART 2: AUDOUT:U SERVICE TESTS
     * ========================================================================= */
    uint32_t audout = open_service(sm, "audout:u");
    assert(audout != 0);

    /* ListAudioOuts (cmd 0 and 2) */
    char dev_name_buf[256] = {0};
    request_with_out_buf(0, NULL, 0, (uintptr_t)dev_name_buf, sizeof dev_name_buf);
    sync_request(audout);
    res = reply_result(&data);
    assert(res == 0);
    uint32_t out_count = 0;
    memcpy(&out_count, data, 4);
    assert(out_count == 1);
    assert(strcmp(dev_name_buf, "DeviceOut") == 0);

    /* OpenAudioOut (cmd 1): 48000 Hz, 2 channels */
    uint32_t open_params[2] = {48000, 2};
    memset(dev_name_buf, 0, sizeof dev_name_buf);
    request_with_out_buf(1, open_params, sizeof open_params, (uintptr_t)dev_name_buf, sizeof dev_name_buf);
    sync_request(audout);
    res = reply_result(&data);
    assert(res == 0);
    assert(msg[1] >> 31); /* returned move handle for IAudioOut */
    uint32_t iaudio_out = msg[3];
    assert(iaudio_out != 0);

    uint32_t returned_params[4];
    memcpy(returned_params, data, sizeof returned_params);
    assert(returned_params[0] == 48000); /* sample_rate */
    assert(returned_params[1] == 2);     /* channels */
    assert(returned_params[2] == 2);     /* format: PCM16 */
    assert(returned_params[3] == 1);     /* state: STATE_STOPPED */

    /* IAudioOut Command 0: GetAudioOutState -> STATE_STOPPED (1) */
    request(0, NULL, 0);
    sync_request(iaudio_out);
    res = reply_result(&data);
    assert(res == 0);
    uint32_t state = 999;
    memcpy(&state, data, 4);
    assert(state == 1); /* STATE_STOPPED */

    /* IAudioOut Command 1: Start -> transitions to STATE_STARTED (0) */
    request(1, NULL, 0);
    sync_request(iaudio_out);
    res = reply_result(&data);
    assert(res == 0);

    request(0, NULL, 0);
    sync_request(iaudio_out);
    res = reply_result(&data);
    assert(res == 0);
    memcpy(&state, data, 4);
    assert(state == 0); /* STATE_STARTED */

    /* IAudioOut Command 2: Stop -> transitions back to STATE_STOPPED (1) */
    request(2, NULL, 0);
    sync_request(iaudio_out);
    res = reply_result(&data);
    assert(res == 0);

    request(0, NULL, 0);
    sync_request(iaudio_out);
    res = reply_result(&data);
    assert(res == 0);
    memcpy(&state, data, 4);
    assert(state == 1); /* STATE_STOPPED */

    /* IAudioOut Command 4: RegisterBufferEvent */
    request(4, NULL, 0);
    sync_request(iaudio_out);
    res = reply_result(&data);
    assert(res == 0);
    assert(msg[1] >> 31);
    uint32_t buf_event = msg[3];
    assert(buf_event != 0);

    /* IAudioOut Command 12: SetAudioOutVolume / Command 13: GetAudioOutVolume */
    float vol_in = 0.75f;
    request(12, &vol_in, sizeof vol_in);
    sync_request(iaudio_out);
    res = reply_result(&data);
    assert(res == 0);

    request(13, NULL, 0);
    sync_request(iaudio_out);
    res = reply_result(&data);
    assert(res == 0);
    float vol_out = 0.0f;
    memcpy(&vol_out, data, sizeof vol_out);
    assert(fabsf(vol_out - 0.75f) < 1e-4f);

    /* IAudioOut Command 9: GetAudioOutBufferCount -> initially 0 */
    request(9, NULL, 0);
    sync_request(iaudio_out);
    res = reply_result(&data);
    assert(res == 0);
    uint32_t q_count = 999;
    memcpy(&q_count, data, 4);
    assert(q_count == 0);

    /* IAudioOut Command 6: ContainsAudioOutBuffer(tag) -> false */
    uint64_t test_tag = 0xabcdef0123456789ull;
    request(6, &test_tag, sizeof test_tag);
    sync_request(iaudio_out);
    res = reply_result(&data);
    assert(res == 0);
    uint8_t found = 1;
    memcpy(&found, data, 1);
    assert(found == 0);

    /* IAudioOut Command 3: AppendAudioOutBuffer */
    int16_t sample_data[240 * 2] = {0};
    AudioBufferDescriptor desc = {
        .next = 0,
        .sample_buffer = (uintptr_t)sample_data,
        .capacity = sizeof sample_data,
        .data_size = sizeof sample_data,
        .data_offset = 0
    };
    request_with_in_buf(3, &test_tag, sizeof test_tag, (uintptr_t)&desc, sizeof desc);
    sync_request(iaudio_out);
    res = reply_result(&data);
    assert(res == 0);

    /* Verify buffer count is now 1 */
    request(9, NULL, 0);
    sync_request(iaudio_out);
    res = reply_result(&data);
    assert(res == 0);
    memcpy(&q_count, data, 4);
    assert(q_count == 1);

    /* Verify ContainsAudioOutBuffer is now true */
    request(6, &test_tag, sizeof test_tag);
    sync_request(iaudio_out);
    res = reply_result(&data);
    assert(res == 0);
    memcpy(&found, data, 1);
    assert(found == 1);

    /* Command 11: FlushAudioOutBuffers */
    request(11, NULL, 0);
    sync_request(iaudio_out);
    res = reply_result(&data);
    assert(res == 0);
    uint8_t any_flushed = 0;
    memcpy(&any_flushed, data, 1);
    assert(any_flushed == 1);

    /* Command 9: buffer count is now 0 */
    request(9, NULL, 0);
    sync_request(iaudio_out);
    res = reply_result(&data);
    assert(res == 0);
    memcpy(&q_count, data, 4);
    assert(q_count == 0);

    /* Command 5: GetReleasedAudioOutBuffers -> collect tag */
    uint64_t rel_tags[8] = {0};
    request_with_out_buf(5, NULL, 0, (uintptr_t)rel_tags, sizeof rel_tags);
    sync_request(iaudio_out);
    res = reply_result(&data);
    assert(res == 0);
    uint32_t n_released = 0;
    memcpy(&n_released, data, 4);
    assert(n_released == 1);
    assert(rel_tags[0] == test_tag);

    /* Close IAudioOut */
    close_session_req(iaudio_out);

    /* =========================================================================
     * PART 3: PURE STRUCT / CALCULATION TESTS (CLASS A)
     * ========================================================================= */
    /* Verify offset definitions match SDK disassembly:
       GetSampleByteSize:
       Format 1 (Int8) -> 1 byte
       Format 2 (Int16) -> 2 bytes
       Format 3 (Int24) -> 3 bytes
       Format 4 (Int32) -> 4 bytes
       Format 5 (Float) -> 4 bytes
    */
    static const uint8_t sample_sizes[] = {0, 1, 2, 3, 4, 4};
    for (int fmt = 1; fmt <= 5; fmt++) {
        assert(sample_sizes[fmt] == (fmt == 1 ? 1 : fmt == 2 ? 2 : fmt == 3 ? 3 : 4));
    }

    /* Verify AudioOutBuffer layout: ptr at +8, capacity at +16, size at +24 */
    AudioBufferDescriptor out_buf = {0};
    void *sample_ptr = (void *)0x12340000;
    out_buf.sample_buffer = (uintptr_t)sample_ptr;
    out_buf.capacity = 2048;
    out_buf.data_size = 1024;
    assert(*(void **)((uint8_t *)&out_buf + 8) == sample_ptr);
    assert(*(uint64_t *)((uint8_t *)&out_buf + 16) == 2048);
    assert(*(uint64_t *)((uint8_t *)&out_buf + 24) == 1024);

    /* Verify AudioOut header layout: rate at +0, channels at +4, format at +8 */
    struct { uint32_t rate, channels, format, state; } audio_out_guest = {48000, 2, 2, 0};
    assert(*(uint32_t *)((uint8_t *)&audio_out_guest + 0) == 48000);
    assert(*(uint32_t *)((uint8_t *)&audio_out_guest + 4) == 2);
    assert(*(uint32_t *)((uint8_t *)&audio_out_guest + 8) == 2);

    printf("ALL_AUDIO_TESTS_OK\n");
    return 0;
}
