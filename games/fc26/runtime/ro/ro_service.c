/* ldr:ro and ro:1 (nn::ro::detail::IRoInterface; commands and arguments from switchbrew "RO services"), answered in
   process over ipc.c. On the console this service only checks an NRO against the NRRs the process registered and maps
   it; relocating it and resolving its imports is the work of the game's own nn::ro library, which runs natively here
   (caminho A in games/fc26/docs/ESTORIA3_NUVEM.md). The image mapped is the module's rewrite made ahead of time
   (ro_module.c). ldr:ro takes NRRs of kind User, ro:1 of kind JitPlugin. Unknown commands stop the runtime. */
#include "../runtime.h"
#include "../ipc.h"
#include "../game_version.h"
#include "ro_core.h"
#include "ro_module.h"
#include "ro_sha256.h"
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { const char *name; int kind; } RoSession;
typedef struct { uint64_t address, size; uint32_t count; uint8_t kind, *hashes; } Nrr;
typedef struct { uint64_t base, address, size, bss_address, bss_size; uint8_t module_id[32]; } Nro;

/* One process context, owned by the session that registered the process (as the service keeps one per process). */
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static struct { RoSession *owner; uint64_t pid; uint32_t process; Nrr nrr[RO_MAX_NRR]; Nro nro[RO_MAX_NRO]; } context;

static int aligned(uint64_t x) { return !(x & (RO_GUEST_PAGE - 1)); }
static uint32_t check_range(uint64_t address, uint64_t size, int nonzero) {
    if (!aligned(address)) return RO_INVALID_ADDRESS;
    if ((nonzero && !size) || !aligned(size) || address + size < address) return RO_INVALID_SIZE;
    return 0;
}

static uint32_t register_process(RoSession *owner, int has_pid, uint32_t process_h) {
    if (context.owner) return RO_INVALID_SESSION;
    if (!has_pid || process_h == 0) return RO_INVALID_PROCESS;
    context.owner = owner; context.pid = 1; context.process = process_h;
    return 0;
}

static uint32_t check_session(RoSession *owner, int has_pid, uint32_t process_h) {
    if (!context.owner || context.owner != owner) return RO_INVALID_PROCESS;
    if (!has_pid || process_h == 0 || process_h != context.process) return RO_INVALID_PROCESS;
    return 0;
}

static uint32_t register_nrr(uint64_t address, uint64_t size, int kind) {
    uint32_t r = check_range(address, size, 1);
    if (r) return r;
    Nrr *slot = NULL;
    for (unsigned i = 0; i < RO_MAX_NRR && !slot; i++) if (!context.nrr[i].hashes) slot = &context.nrr[i];
    if (!slot) return RO_TOO_MANY_NRR;
    RoNrr nrr;
    if ((r = ro_nrr_parse(ipc_guest(address, size), size, &nrr)) || (r = ro_nrr_check(&nrr, GAME_TITLE_ID, kind))) {
        if (r == RO_INVALID_NRR && nrr.program_id && nrr.program_id != GAME_TITLE_ID)
            fprintf(stderr, "[fc26-ro] NRR for program %016llx, the game is %016llx\n", (unsigned long long)nrr.program_id, (unsigned long long)GAME_TITLE_ID);
        return r;
    }
    /* The console maps the NRR away from the process while it is registered; a copy of the list does the same here. */
    uint8_t *hashes = malloc(32 * (size_t)nrr.num_hashes + 1);
    if (!hashes) runtime_fail("NRR hash list allocation");
    memcpy(hashes, nrr.hashes, 32 * (size_t)nrr.num_hashes);
    *slot = (Nrr){address, size, nrr.num_hashes, nrr.kind, hashes};
    fprintf(stderr, "[fc26-ro] NRR registered: %u module hashes, kind %u%s\n", nrr.num_hashes, nrr.kind,
            nrr.sorted ? "" : " (NOT sorted: the service's binary search may miss modules)");
    return 0;
}

static uint32_t unregister_nrr(uint64_t address) {
    if (!aligned(address)) return RO_INVALID_ADDRESS;
    for (unsigned i = 0; i < RO_MAX_NRR; i++)
        if (context.nrr[i].hashes && context.nrr[i].address == address) {
            free(context.nrr[i].hashes); memset(&context.nrr[i], 0, sizeof context.nrr[i]);
            return 0;
        }
    return RO_NOT_REGISTERED;
}

static uint32_t map_nro(uint64_t address, uint64_t size, uint64_t bss_address, uint64_t bss_size, uint64_t *out) {
    uint32_t r;
    if ((r = check_range(address, size, 1)) || (r = check_range(bss_address, bss_size, 0))) return r;
    if (size + bss_size < size) return RO_INVALID_SIZE;
    Nro *slot = NULL;
    for (unsigned i = 0; i < RO_MAX_NRO && !slot; i++) if (!context.nro[i].base) slot = &context.nro[i];
    if (!slot) return RO_TOO_MANY_NRO;
    const uint8_t *bytes = ipc_guest(address, size);
    RoNro header;
    if ((r = ro_nro_parse(bytes, size, bss_size, &header))) return r;
    uint8_t hash[32]; char hex[65];
    ro_sha256(bytes, (size_t)size, hash); ro_hex(hash, 32, hex);
    int authorized = 0;
    for (unsigned i = 0; i < RO_MAX_NRR && !authorized; i++)
        authorized = context.nrr[i].hashes && ro_nrr_has(context.nrr[i].hashes, context.nrr[i].count, hash);
    if (!authorized) { fprintf(stderr, "[fc26-ro] NRO sha256=%s is in no registered NRR\n", hex); return RO_NOT_AUTHORIZED; }
    for (unsigned i = 0; i < RO_MAX_NRO; i++)
        if (context.nro[i].base && !memcmp(context.nro[i].module_id, header.module_id, 32)) return RO_ALREADY_LOADED;
    uint64_t base;
    if ((r = ro_module_map(bytes, &header, hash, &base))) return r;
    *slot = (Nro){base, address, size, bss_address, bss_size, {0}};
    memcpy(slot->module_id, header.module_id, 32);
    *out = base;
    return 0;
}

static uint32_t unmap_nro(uint64_t base) {
    if (!aligned(base)) return RO_INVALID_ADDRESS;
    for (unsigned i = 0; i < RO_MAX_NRO; i++)
        if (context.nro[i].base && context.nro[i].base == base) {
            memset(&context.nro[i], 0, sizeof context.nro[i]);
            return ro_module_unmap(base);
        }
    return RO_NOT_LOADED;
}

static const char *command_name(unsigned cmd) {
    switch (cmd) {
    case 0: return "MapManualLoadModuleMemory";  case 1: return "UnmapManualLoadModuleMemory";
    case 2: return "RegisterModuleInfo";         case 3: return "UnregisterModuleInfo";
    case 4: return "RegisterProcessHandle";      case 10: return "RegisterModuleInfoWithUserProcessHandle";
    default: return "?";
    }
}

static void ro_handler(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {
    RoSession *session = s->state;
    if (rq->cmd > 4 && rq->cmd != 10) ipc_unimplemented(s, rq);
    /* Every command starts with the u64 pid placeholder; the pid itself comes in the PID descriptor. */
    uint64_t a[4] = {0};
    for (unsigned i = 0; i < 4 && 8 * (i + 2) <= rq->data_size; i++) a[i] = IPC_ARG(rq, uint64_t, 8 * (i + 1));
    uint64_t out = 0;
    uint32_t r;
    pthread_mutex_lock(&lock);
    if (rq->cmd == 4) {
        r = register_process(session, rq->has_pid, rq->ncopy ? rq->copy[0] : 0);
    } else {
        uint32_t proc = (rq->cmd == 10) ? (rq->ncopy ? rq->copy[0] : 0) : context.process;
        r = check_session(session, rq->has_pid, proc);
        if (!r) switch (rq->cmd) {
        case 0: r = map_nro(a[0], a[1], a[2], a[3], &out); break;
        case 1: r = unmap_nro(a[0]); break;
        case 2: r = register_nrr(a[0], a[1], RO_NRR_USER); break;                 /* [7.0.0+] User only */
        case 3: r = unregister_nrr(a[0]); break;
        default: r = register_nrr(a[0], a[1], session->kind); break;             /* 10 */
        }
    }
    pthread_mutex_unlock(&lock);
    fprintf(stderr, "[fc26-ro] %s %s(%#llx, %#llx, %#llx, %#llx) -> %#x", session->name, command_name(rq->cmd),
            (unsigned long long)a[0], (unsigned long long)a[1], (unsigned long long)a[2], (unsigned long long)a[3], r);
    if (rq->cmd == 0 && !r) fprintf(stderr, " address %#llx", (unsigned long long)out);
    fputc('\n', stderr);
    rs->result = r;
    if (rq->cmd == 0 && !r) IPC_OUT(rs, out);
}

static void *open_user(void) { RoSession *s = calloc(1, sizeof *s); if (!s) runtime_fail("ro session"); *s = (RoSession){"ldr:ro", RO_NRR_USER}; return s; }
static void *open_jit(void) { RoSession *s = calloc(1, sizeof *s); if (!s) runtime_fail("ro session"); *s = (RoSession){"ro:1", RO_NRR_JIT_PLUGIN}; return s; }

/* Closing the session that registered the process ends its context: NRRs are dropped, modules stay mapped (code may
   still run from them; the console does not unmap them either when the context goes). */
static void close_session(void *state) {
    pthread_mutex_lock(&lock);
    if (context.owner == state) {
        for (unsigned i = 0; i < RO_MAX_NRR; i++) {
            free(context.nrr[i].hashes);
            context.nrr[i].hashes = NULL;
        }
        memset(context.nrr, 0, sizeof context.nrr);
        context.owner = NULL;
        context.pid = 0;
        context.process = 0;
    }
    pthread_mutex_unlock(&lock);
    free(state);
}

__attribute__((constructor)) static void register_ro_services(void) {
    runtime_ipc_register("ldr:ro", ro_handler, open_user, close_session);
    runtime_ipc_register("ro:1", ro_handler, open_jit, close_session);
}
