/* ldr:ro / ro:1 (games/fc26/runtime/ro/ro_service.c, ro_module.c) against synthetic files written by
   tests/test_fc26_ro_runtime.py. The rest of the runtime is replaced by the stand-ins below; requests are built the way
   ipc.c hands them to a service (CMIF arguments after the pid placeholder, the PID descriptor, copy handles).
   Modes: "flow <dir>" (everything that must work and every refusal), "missing <dir>" (an authorized NRO without a
   rewritten image stops the runtime), "tampered <dir>" (a rewritten image that does not match the manifest stops it),
   "probe <dir>" (ro_module_probe, the probe-ro mode, over every image in the manifest). */
#include "runtime.h"
#include "ipc.h"
#include "ro/ro_core.h"
#include "ro/ro_module.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <sys/mman.h>
#if defined(__APPLE__)
#include <mach/mach.h>
#include <mach/mach_vm.h>
#endif

/* ---------- stand-ins for the runtime ---------- */
pthread_key_t runtime_keys[8];
_Noreturn void runtime_fail(const char *message) { fprintf(stderr, "[test] runtime_fail: %s\n", message); fflush(stderr); exit(3); }
void runtime_missing(const char *format, ...) {
    va_list va;
    va_start(va, format);
    fprintf(stderr, "[fc26-missing] ");
    vfprintf(stderr, format, va);
    fputc('\n', stderr);
    va_end(va);
}
static LateSlot test_late_slots_storage[16];
static unsigned test_late_slots_count = 0;

LateSlot *runtime_late_slots(unsigned *count) {
    if (count) *count = test_late_slots_count;
    return test_late_slots_storage;
}
static uint64_t stub_class_type_info[4], stub_allocate;
static void *fake_g_pAutoLoadList = NULL;
static void *fake_g_pManualLoadList = NULL;
static void *fake_g_pLookupGlobalAutoFunctionPointer = NULL;
static void *fake_g_pLookupGlobalManualFunctionPointer = NULL;
static void *fake_g_pRoDebugFlag = NULL;
static void stub_mutex_lock(void) {}
static void stub_guard_override(void) {}
void *runtime_symbol(const char *name) {
    const char *hidden = getenv("TEST_HIDE_SYMBOL");   /* probe mode: an import main / sdk would not export */
    if (hidden && !strcmp(name, hidden)) return NULL;
    if (!strcmp(name, "pthread_mutex_lock")) return (void *)stub_mutex_lock;
    if (!strcmp(name, "_ZTVN10__cxxabiv117__class_type_infoE")) return stub_class_type_info;
    if (!strcmp(name, "_ZN2nn3mem17StandardAllocator8AllocateEm")) return &stub_allocate;
    if (!strcmp(name, "__cxa_guard_acquire")) return (void *)stub_mutex_lock;   /* overridden below: must not be used */
    if (!strcmp(name, "_ZN2nn2ro6detail15g_pAutoLoadListE")) return &fake_g_pAutoLoadList;
    if (!strcmp(name, "_ZN2nn2ro6detail17g_pManualLoadListE")) return &fake_g_pManualLoadList;
    if (!strcmp(name, "_ZN2nn2ro6detail34g_pLookupGlobalAutoFunctionPointerE")) return &fake_g_pLookupGlobalAutoFunctionPointer;
    if (!strcmp(name, "_ZN2nn2ro6detail36g_pLookupGlobalManualFunctionPointerE")) return &fake_g_pLookupGlobalManualFunctionPointer;
    if (!strcmp(name, "_ZN2nn2ro6detail14g_pRoDebugFlagE")) return &fake_g_pRoDebugFlag;
    return NULL;
}
void *runtime_override(const char *name) { return !strcmp(name, "__cxa_guard_acquire") ? (void *)stub_guard_override : NULL; }
void *runtime_hle_wrap_named(void *fn, const char *name) { (void)name; return fn; }
uint64_t runtime_now_ns(void) { return 625000; }   /* a timer gate then reads 12000 ticks */
static unsigned svc_seen; static const char *svc_module; static uint64_t svc_offset;
uint64_t runtime_svc(unsigned num, uint64_t *regs, const char *module, uint64_t offset) {
    svc_seen = num; svc_module = module; svc_offset = offset; regs[0] = 0; return 0;
}

typedef struct { const char *name; IpcHandler handler; IpcOpen open; void (*close)(void *); } Registered;
static Registered registered[4]; static unsigned nregistered;
void runtime_ipc_register(const char *name, IpcHandler handler, IpcOpen open, void (*close)(void *)) {
    if (nregistered == 4) runtime_fail("test registry full");
    registered[nregistered++] = (Registered){name, handler, open, close};
}
const void *ipc_arg(const IpcRequest *rq, uint32_t off, uint32_t n) {
    if (off + n > rq->data_size) runtime_fail("IPC argument out of range");
    return rq->data + off;
}
void ipc_out(IpcResponse *rs, const void *p, uint32_t n) {
    if (rs->data_size + n > sizeof rs->data) runtime_fail("IPC response too large");
    memcpy(rs->data + rs->data_size, p, n); rs->data_size += n;
}
void *ipc_guest(uint64_t addr, uint64_t size) { if (!addr && size) runtime_fail("IPC null buffer"); return (void *)(uintptr_t)addr; }
_Noreturn void ipc_unimplemented(const IpcSession *s, const IpcRequest *rq) { fprintf(stderr, "[test] %s command %u\n", s->name, rq->cmd); runtime_fail("IPC command not implemented"); }

/* ---------- helpers ---------- */
static unsigned failures;
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "%s:%d: CHECK(%s)\n", __FILE__, __LINE__, #c); failures++; } } while (0)
#define CHECK_EQ(a, b) do { unsigned long long x_ = (unsigned long long)(a), y_ = (unsigned long long)(b); \
    if (x_ != y_) { fprintf(stderr, "%s:%d: %s = %#llx, expected %#llx\n", __FILE__, __LINE__, #a, x_, y_); failures++; } } while (0)

static const char *dir;
static uint8_t *load(const char *name, size_t *size) {   /* page aligned, as the game's buffers are */
    char path[4096]; snprintf(path, sizeof path, "%s/%s", dir, name);
    FILE *f = fopen(path, "rb"); if (!f) { perror(path); exit(2); }
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    void *p = NULL;
    if (posix_memalign(&p, 0x1000, ((size_t)n + 0xfff) & ~(size_t)0xfff) || fread(p, 1, (size_t)n, f) != (size_t)n) exit(2);
    fclose(f); *size = (size_t)n; return p;
}
static unsigned long long expect(const char *key) {
    size_t n; char *text = (char *)load("expect.txt", &n), *line = text;
    text[n - 1] = 0;
    for (; line && *line; line = strchr(line, '\n') ? strchr(line, '\n') + 1 : NULL) {
        size_t k = strlen(key);
        if (!strncmp(line, key, k) && line[k] == ' ') { unsigned long long v = strtoull(line + k + 1, NULL, 0); free(text); return v; }
    }
    fprintf(stderr, "expect.txt has no %s\n", key); exit(2);
}
static uint64_t word(uint64_t address) { uint64_t v; memcpy(&v, (const void *)(uintptr_t)address, 8); return v; }

/* The host protection of the page holding address: r/w/x bits, -1 when nothing is mapped there. */
static int host_prot(uint64_t address) {
#if defined(__APPLE__)
    mach_vm_address_t a = address; mach_vm_size_t size = 0; vm_region_basic_info_data_64_t info;
    mach_msg_type_number_t count = VM_REGION_BASIC_INFO_COUNT_64; mach_port_t object = 0;
    if (mach_vm_region(mach_task_self(), &a, &size, VM_REGION_BASIC_INFO_64, (vm_region_info_t)&info, &count, &object) != KERN_SUCCESS || a > address) return -1;
    return (info.protection & VM_PROT_READ ? 1 : 0) | (info.protection & VM_PROT_WRITE ? 2 : 0) | (info.protection & VM_PROT_EXECUTE ? 4 : 0);
#else
    FILE *f = fopen("/proc/self/maps", "r"); char line[512]; int prot = -1;
    while (f && fgets(line, sizeof line, f)) {
        unsigned long long lo, hi; char perms[8];
        if (sscanf(line, "%llx-%llx %7s", &lo, &hi, perms) == 3 && address >= lo && address < hi) {
            prot = (perms[0] == 'r' ? 1 : 0) | (perms[1] == 'w' ? 2 : 0) | (perms[2] == 'x' ? 4 : 0); break;
        }
    }
    if (f) fclose(f);
    return prot;
#endif
}

static IpcSession open_session(const char *name) {
    for (unsigned i = 0; i < nregistered; i++)
        if (!strcmp(registered[i].name, name)) return (IpcSession){registered[i].name, registered[i].handler, registered[i].open(), registered[i].close, NULL};
    fprintf(stderr, "service %s not registered\n", name); exit(2);
}
/* One request: pid in the PID descriptor, the u64 placeholder, then the command's u64 arguments. */
static uint32_t call_opt(IpcSession *s, unsigned cmd, int has_pid, uint64_t pid, int handle, uint32_t copy_h, uint64_t a0, uint64_t a1, uint64_t a2, uint64_t a3, unsigned nargs, uint64_t *out) {
    uint64_t words[5] = {0, a0, a1, a2, a3};
    IpcRequest rq; memset(&rq, 0, sizeof rq);
    rq.type = 4; rq.cmd = cmd; rq.has_pid = has_pid; rq.pid = pid;
    if (handle) { rq.ncopy = 1; rq.copy[0] = copy_h ? copy_h : 0xffff8001u; }   /* CUR_PROCESS_HANDLE */
    rq.data = (const uint8_t *)words; rq.data_size = 8 * (1 + nargs);
    IpcResponse rs; memset(&rs, 0, sizeof rs);
    s->handler(s, &rq, &rs);
    if (out) { *out = 0; if (rs.data_size == 8) memcpy(out, rs.data, 8); }
    if (rs.result) CHECK_EQ(rs.data_size, 0);
    return rs.result;
}
static uint32_t call(IpcSession *s, unsigned cmd, uint64_t pid, int handle, uint64_t a0, uint64_t a1, uint64_t a2, uint64_t a3, unsigned nargs, uint64_t *out) {
    return call_opt(s, cmd, 1, pid, handle, 0, a0, a1, a2, a3, nargs, out);
}
#define PID 0x51
static uint64_t ptr(const void *p) { return (uint64_t)(uintptr_t)p; }

static void check_mapping(uint64_t base) {
    size_t size; uint8_t *patched = load("m.patched.bin", &size);
    CHECK_EQ(base % 0x4000, 0);
    CHECK(!memcmp((const void *)(uintptr_t)base, patched, expect("key_off")));             /* image up to the key page */
    CHECK(!memcmp((const uint8_t *)(uintptr_t)base + expect("patch_off"), patched + expect("patch_off"), size - expect("patch_off")));
    for (unsigned i = 0; i < 8; i++) CHECK_EQ(word(base + expect("key_off") + 8 * i), (uint64_t)runtime_keys[i] * 8);
    free(patched);
    uint64_t data = expect("data"), key = expect("key_off"), patch = expect("patch_off");
    CHECK_EQ(host_prot(base), 5); CHECK_EQ(host_prot(base + expect("ro")), 1); CHECK_EQ(host_prot(base + data), 3);
    CHECK_EQ(host_prot(base + key - 1), 3); CHECK_EQ(host_prot(base + key), 1); CHECK_EQ(host_prot(base + patch), 5);
    if (patch > key + 0x4000) CHECK_EQ(host_prot(base + key + 0x4000), 0);

    Gate g; const char *name;
    CHECK(ro_module_gate(base + expect("gate0_ret"), &g, &name));
    CHECK_EQ(g.ret, expect("gate0_ret")); CHECK_EQ(g.arg, expect("gate0_arg")); CHECK(!strcmp(name, "m"));
    CHECK(!ro_module_gate(base + 0x100, &g, &name));
    uint64_t regs[32] = {0};
    CHECK(ro_module_dispatch(base + expect("gate_svc_ret"), regs));
    CHECK_EQ(svc_seen, 1); CHECK(svc_module && !strcmp(svc_module, "m")); CHECK_EQ(svc_offset, 0x108);
    CHECK(ro_module_dispatch(base + expect("gate_timer_ret"), regs));
    CHECK_EQ(regs[1], 12000);                                   /* x1 of mrs x1, cntpct_el0 */
    CHECK(!ro_module_dispatch(base + 0x104, regs));
    uint64_t off; CHECK(ro_module_offset(base + 0x130, &name, &off) && off == 0x130 && !strcmp(name, "m"));
    CHECK(!ro_module_offset(ptr(&g), &name, &off));
    CHECK(ro_module_symbol(base, "nro_export_fn") == (void *)(uintptr_t)(base + 0x130));
    CHECK(ro_module_symbol(base, "pthread_mutex_lock") == NULL);

    uint64_t qbase, qsize; unsigned state, perm, attr;
    CHECK(ro_module_query(base + 0x104, &qbase, &qsize, &state, &perm, &attr));
    CHECK_EQ(qbase, base); CHECK_EQ(qsize, expect("ro")); CHECK_EQ(state, RO_STATE_ALIAS_CODE); CHECK_EQ(perm, 5);
    CHECK(ro_module_query(base + data, &qbase, &qsize, &state, &perm, &attr));
    CHECK_EQ(state, RO_STATE_ALIAS_CODE_DATA); CHECK_EQ(perm, 3); CHECK_EQ(qsize, expect("nro_size") + expect("bss_size") - data);
    CHECK(!ro_module_query(base + key, &qbase, &qsize, &state, &perm, &attr));          /* host-only key page */

    uint64_t end = expect("nro_size") + expect("bss_size");
    CHECK_EQ(ro_module_permission(base + data, 0x1000, 1), 0);
    CHECK_EQ(host_prot(base + data), 3);                         /* three other guest pages share the host page */
    CHECK_EQ(ro_module_permission(base + data, end - data, 1), 0);
    CHECK_EQ(host_prot(base + data), 1);
    CHECK_EQ(word(base + expect("export_data")), 0x1234);        /* still readable */
    CHECK_EQ(ro_module_permission(base + data, end - data, 3), 0);
    CHECK_EQ(host_prot(base + data), 3);
    CHECK_EQ(ro_module_lock_permission(base + data, 0x1000, 16, 16), 0);
    CHECK_EQ(ro_module_permission(base + data, 0x1000, 1), RO_SVC_INVALID_MEMORY);
    CHECK_EQ(ro_module_permission(base, 0x1000, 1), RO_SVC_INVALID_MEMORY);              /* text */
    CHECK_EQ(ro_module_permission(ptr(&g) & ~0xfffULL, 0x1000, 1), RO_SVC_INVALID_MEMORY); /* not a module */
    CHECK(ro_module_bytes() >= patch);
}

static void link_by_host(void) {
    size_t size; uint8_t *nro = load("notls.nro", &size), *nrr = NULL;
    size_t nrr_size; nrr = load("notls.nrr", &nrr_size);
    IpcSession s = open_session("ldr:ro");
    CHECK_EQ(call(&s, 4, PID, 1, 0, 0, 0, 0, 0, NULL), 0);
    CHECK_EQ(call(&s, 2, PID, 0, ptr(nrr), nrr_size, 0, 0, 2, NULL), 0);
    void *bss; if (posix_memalign(&bss, 0x1000, expect("bss_size"))) exit(2);
    uint64_t base;
    CHECK_EQ(call(&s, 0, PID, 0, ptr(nro), size, ptr(bss), expect("bss_size"), 4, &base), 0);
    char err[256];
    CHECK_EQ(ro_module_link_host(base, err, sizeof err), 0);
    CHECK_EQ(word(base + expect("init_array")), base + 0x140);
    CHECK_EQ(word(base + expect("far")), base + 0x4100);
    CHECK_EQ(word(base + expect("g_abs_import")), ptr(stub_class_type_info) + 16);
    CHECK_EQ(word(base + expect("g_abs_local")), base + expect("export_data"));
    CHECK_EQ(word(base + expect("g_glob")), ptr(&stub_allocate));
    CHECK_EQ(word(base + expect("g_weak")), 0);
    CHECK_EQ(word(base + expect("g_jump0")), ptr((void *)stub_mutex_lock));
    CHECK_EQ(word(base + expect("g_jump1")), ptr((void *)stub_guard_override));   /* runtime_override wins, as in loader.c */
    CHECK(ro_module_link_host(base, err, sizeof err) != 0 && strstr(err, "already"));
    CHECK_EQ(call(&s, 1, PID, 0, base, 0, 0, 0, 1, NULL), 0);
    s.close(s.state);
    free(nro); free(nrr); free(bss);
}

static void test_sdk_init(void) {
    CHECK(fake_g_pAutoLoadList == NULL);
    CHECK(fake_g_pManualLoadList == NULL);
    CHECK(fake_g_pLookupGlobalAutoFunctionPointer == NULL);
    CHECK(fake_g_pLookupGlobalManualFunctionPointer == NULL);
    CHECK(fake_g_pRoDebugFlag == NULL);

    ro_module_init_sdk();

    CHECK(fake_g_pAutoLoadList != NULL);
    struct { void *next; void *prev; } *al = fake_g_pAutoLoadList;
    CHECK(al->next == (void *)al && al->prev == (void *)al);

    CHECK(fake_g_pManualLoadList != NULL);
    struct { void *next; void *prev; } *ml = fake_g_pManualLoadList;
    CHECK(ml->next == (void *)ml && ml->prev == (void *)ml);

    CHECK(fake_g_pRoDebugFlag != NULL);
    uint8_t *df = (uint8_t *)fake_g_pRoDebugFlag;
    CHECK_EQ(*df, 0);

    CHECK(fake_g_pLookupGlobalManualFunctionPointer != NULL);
    void **mf = (void **)fake_g_pLookupGlobalManualFunctionPointer;
    *mf = (void *)0x12345678ULL;
    CHECK_EQ(*mf, (void *)0x12345678ULL);

    /* The sdk calls this variable's value itself (sdk+0x14ab34/0x14c62c: ldr x8, [x8]; blr x8): it holds the function. */
    CHECK(fake_g_pLookupGlobalAutoFunctionPointer != NULL);
    typedef void *(*LookupFn)(const char *);
    LookupFn lookup = (LookupFn)fake_g_pLookupGlobalAutoFunctionPointer;

    CHECK_EQ(lookup("__cxa_guard_acquire"), (void *)stub_guard_override);
    CHECK_EQ(lookup("pthread_mutex_lock"), (void *)stub_mutex_lock);
    CHECK_EQ(lookup("nonexistent_symbol_42"), NULL);
}

static void flow(void) {
    size_t nro_size, user_size, jit_size, other_size, without_size;
    uint8_t *nro = load("m.nro", &nro_size), *user = load("user.nrr", &user_size), *jit = load("jit.nrr", &jit_size);
    uint8_t *other = load("other_program.nrr", &other_size), *without = load("without.nrr", &without_size);
    uint64_t bss_size = expect("bss_size"), base = 0, again = 0;
    void *bss; if (posix_memalign(&bss, 0x1000, bss_size)) exit(2);
    IpcSession u = open_session("ldr:ro"), j = open_session("ro:1");

    CHECK_EQ(call(&u, 2, PID, 0, ptr(user), user_size, 0, 0, 2, NULL), RO_INVALID_PROCESS);   /* before RegisterProcessHandle */
    CHECK_EQ(call(&u, 4, PID, 0, 0, 0, 0, 0, 0, NULL), RO_INVALID_PROCESS);                    /* no process handle */
    CHECK_EQ(call(&u, 4, PID, 1, 0, 0, 0, 0, 0, NULL), 0);
    CHECK_EQ(call(&u, 4, PID, 1, 0, 0, 0, 0, 0, NULL), RO_INVALID_SESSION);
    CHECK_EQ(call(&j, 4, PID, 1, 0, 0, 0, 0, 0, NULL), RO_INVALID_SESSION);                    /* one context per process */
    CHECK_EQ(call(&j, 2, PID, 0, ptr(user), user_size, 0, 0, 2, NULL), RO_INVALID_PROCESS);
    CHECK_EQ(call_opt(&u, 2, 0, PID, 0, 0, ptr(user), user_size, 0, 0, 2, NULL), RO_INVALID_PROCESS); /* missing PID descriptor */

    CHECK_EQ(call(&u, 2, PID, 0, ptr(user) + 8, user_size, 0, 0, 2, NULL), RO_INVALID_ADDRESS);
    CHECK_EQ(call(&u, 2, PID, 0, ptr(user), 0, 0, 0, 2, NULL), RO_INVALID_SIZE);
    CHECK_EQ(call(&u, 2, PID, 0, ptr(jit), jit_size, 0, 0, 2, NULL), RO_INVALID_NRR_KIND);       /* RegisterModuleInfo: User only */
    CHECK_EQ(call(&u, 2, PID, 0, ptr(other), other_size, 0, 0, 2, NULL), RO_INVALID_NRR);        /* another program's NRR */
    CHECK_EQ(call(&u, 2, PID, 0, ptr(without), without_size, 0, 0, 2, NULL), 0);
    CHECK_EQ(call(&u, 0, PID, 0, ptr(nro), nro_size, ptr(bss), bss_size, 4, &base), RO_NOT_AUTHORIZED);
    CHECK_EQ(call(&u, 2, 0, 0, ptr(user), user_size, 0, 0, 2, NULL), 0);                          /* uninitialized/zero pid accepted if has_pid */
    CHECK_EQ(call(&u, 0, PID, 0, ptr(nro), nro_size, ptr(bss), bss_size + 0x1000, 4, &base), RO_INVALID_NRO);
    CHECK_EQ(call(&u, 0, PID, 0, ptr(nro) + 0x10, nro_size, ptr(bss), bss_size, 4, &base), RO_INVALID_ADDRESS);
    CHECK_EQ(call(&u, 0, PID, 0, ptr(nro), nro_size, ptr(bss) + 1, bss_size, 4, &base), RO_INVALID_ADDRESS);
    CHECK_EQ(call(&u, 0, PID, 0, ptr(nro), nro_size + 0x10, ptr(bss), bss_size, 4, &base), RO_INVALID_SIZE);

    CHECK_EQ(call(&u, 0, PID, 0, ptr(nro), nro_size, ptr(bss), bss_size, 4, &base), 0);
    CHECK(base != 0);
    check_mapping(base);
    char err[256];
    CHECK(ro_module_link_host(base, err, sizeof err) != 0 && strstr(err, "TLSDESC"));   /* caminho B stops on TLS */
    CHECK_EQ(call(&u, 0, PID, 0, ptr(nro), nro_size, ptr(bss), bss_size, 4, &again), RO_ALREADY_LOADED);
    CHECK_EQ(call(&u, 1, PID, 0, base + 0x10, 0, 0, 0, 1, NULL), RO_INVALID_ADDRESS);
    CHECK_EQ(call(&u, 1, PID, 0, base, 0, 0, 0, 1, NULL), 0);
    CHECK_EQ(call(&u, 1, PID, 0, base, 0, 0, 0, 1, NULL), RO_NOT_LOADED);
    Gate g; const char *name;
    CHECK(!ro_module_gate(base + expect("gate0_ret"), &g, &name));
    CHECK_EQ(host_prot(base), -1);
    CHECK_EQ(call(&u, 3, PID, 0, ptr(user), 0, 0, 0, 1, NULL), 0);
    CHECK_EQ(call(&u, 3, PID, 0, ptr(user), 0, 0, 0, 1, NULL), RO_NOT_REGISTERED);
    CHECK_EQ(call(&u, 0, PID, 0, ptr(nro), nro_size, ptr(bss), bss_size, 4, &base), RO_NOT_AUTHORIZED);   /* only "without" left */

    u.close(u.state);                                     /* the context goes with its session */
    CHECK_EQ(call(&j, 4, PID, 1, 0, 0, 0, 0, 0, NULL), 0);
    CHECK_EQ(call(&j, 10, PID, 0, ptr(jit), jit_size, 0, 0, 2, NULL), RO_INVALID_PROCESS);       /* needs the process handle */
    CHECK_EQ(call_opt(&j, 10, 1, PID, 1, 0x1234, ptr(jit), jit_size, 0, 0, 2, NULL), RO_INVALID_PROCESS); /* wrong process handle */
    CHECK_EQ(call(&j, 10, PID, 1, ptr(user), user_size, 0, 0, 2, NULL), RO_INVALID_NRR_KIND);     /* ro:1 takes JitPlugin */
    CHECK_EQ(call(&j, 10, PID, 1, ptr(jit), jit_size, 0, 0, 2, NULL), 0);
    CHECK_EQ(call(&j, 0, PID, 0, ptr(nro), nro_size, ptr(bss), bss_size, 4, &base), 0);

    /* Achado 4 test: close session leaves context.nro[] intact */
    j.close(j.state);
    IpcSession u2 = open_session("ldr:ro");
    CHECK_EQ(call(&u2, 4, PID, 1, 0, 0, 0, 0, 0, NULL), 0);
    CHECK_EQ(call(&u2, 2, PID, 0, ptr(user), user_size, 0, 0, 2, NULL), 0);
    uint64_t remapped;
    CHECK_EQ(call(&u2, 0, PID, 0, ptr(nro), nro_size, ptr(bss), bss_size, 4, &remapped), RO_ALREADY_LOADED);
    CHECK_EQ(call(&u2, 1, PID, 0, base, 0, 0, 0, 1, NULL), 0);
    CHECK_EQ(call(&u2, 1, PID, 0, base, 0, 0, 0, 1, NULL), RO_NOT_LOADED);
    u2.close(u2.state);

    free(nro); free(user); free(jit); free(other); free(without); free(bss);
    link_by_host();
    test_sdk_init();
}

/* An NRO the game may load (its hash is in the NRR) but that has no image: the runtime stops, naming it. */
static void stop_on_map(const char *nro_name) {
    size_t nro_size, nrr_size; uint8_t *nro = load(nro_name, &nro_size), *nrr = load("stranger.nrr", &nrr_size);
    void *bss; if (posix_memalign(&bss, 0x1000, expect("bss_size"))) exit(2);
    IpcSession s = open_session("ldr:ro");
    CHECK_EQ(call(&s, 4, PID, 1, 0, 0, 0, 0, 0, NULL), 0);
    CHECK_EQ(call(&s, 2, PID, 0, ptr(nrr), nrr_size, 0, 0, 2, NULL), 0);
    uint64_t base;
    call(&s, 0, PID, 0, ptr(nro), nro_size, ptr(bss), expect("bss_size"), 4, &base);
    fprintf(stderr, "[test] the map returned instead of stopping\n");
    exit(1);
}

static void test_late_slots(void) {
    size_t nro_size, nrr_size;
    uint8_t *nro = load("late.nro", &nro_size);
    uint8_t *nrr = load("late.nrr", &nrr_size);
    void *bss; if (posix_memalign(&bss, 0x1000, expect("bss_size"))) exit(2);

    /* Allocate page for main's slots and protect as read-only (RELRO) */
    uint64_t *slots_page = mmap(NULL, 0x4000, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
    if (slots_page == MAP_FAILED) exit(2);
    slots_page[0] = 0;
    slots_page[1] = 0;
    if (mprotect(slots_page, 0x4000, PROT_READ) != 0) exit(2);
    CHECK_EQ(host_prot(ptr(slots_page)), 1);

    test_late_slots_storage[0] = (LateSlot){ &slots_page[0], "late_var0", "late" };
    test_late_slots_storage[1] = (LateSlot){ &slots_page[1], "late_var1", "late" };
    test_late_slots_count = 2;

    IpcSession s = open_session("ldr:ro");
    CHECK_EQ(call(&s, 4, PID, 1, 0, 0, 0, 0, 0, NULL), 0);
    CHECK_EQ(call(&s, 2, PID, 0, ptr(nrr), nrr_size, 0, 0, 2, NULL), 0);

    /* Before Map: slots are 0 */
    CHECK_EQ(slots_page[0], 0);
    CHECK_EQ(slots_page[1], 0);

    /* MapManualLoadModuleMemory */
    uint64_t base = 0;
    CHECK_EQ(call(&s, 0, PID, 0, ptr(nro), nro_size, ptr(bss), expect("bss_size"), 4, &base), 0);
    CHECK(base != 0);

    /* After Map: slots hold base + st_value */
    CHECK_EQ(slots_page[0], base + expect("late_var0"));
    CHECK_EQ(slots_page[1], base + expect("late_var1"));

    /* Verify page remained read-only (RELRO preserved) */
    CHECK_EQ(host_prot(ptr(slots_page)), 1);

    /* UnmapManualLoadModuleMemory */
    CHECK_EQ(call(&s, 1, PID, 0, base, 0, 0, 0, 1, NULL), 0);

    /* After Unmap: slots are reset to 0 */
    CHECK_EQ(slots_page[0], 0);
    CHECK_EQ(slots_page[1], 0);

    /* Protection still preserved */
    CHECK_EQ(host_prot(ptr(slots_page)), 1);

    s.close(s.state);
    mprotect(slots_page, 0x4000, PROT_READ | PROT_WRITE);
    munmap(slots_page, 0x4000);
    free(nro); free(nrr); free(bss);
}

static void test_late_missing(void) {
    size_t nro_size, nrr_size;
    uint8_t *nro = load("late.nro", &nro_size);
    uint8_t *nrr = load("late.nrr", &nrr_size);
    void *bss; if (posix_memalign(&bss, 0x1000, expect("bss_size"))) exit(2);

    uint64_t slot = 0;
    test_late_slots_storage[0] = (LateSlot){ &slot, "nonexistent_late_symbol", "late" };
    test_late_slots_count = 1;

    IpcSession s = open_session("ldr:ro");
    CHECK_EQ(call(&s, 4, PID, 1, 0, 0, 0, 0, 0, NULL), 0);
    CHECK_EQ(call(&s, 2, PID, 0, ptr(nrr), nrr_size, 0, 0, 2, NULL), 0);

    uint64_t base = 0;
    call(&s, 0, PID, 0, ptr(nro), nro_size, ptr(bss), expect("bss_size"), 4, &base);
    fprintf(stderr, "[test] the map returned instead of stopping\n");
    exit(1);
}

int main(int argc, char **argv) {
    if (argc != 3) { fprintf(stderr, "usage: %s flow|missing|tampered <directory>\n", argv[0]); return 2; }
    dir = argv[2];
    for (unsigned i = 0; i < 8; i++) if (pthread_key_create(&runtime_keys[i], NULL)) return 2;
    if (!strcmp(argv[1], "flow")) { ro_module_set_dir(dir); flow(); }
    else if (!strcmp(argv[1], "missing")) { ro_module_set_dir(dir); stop_on_map("stranger.nro"); }
    else if (!strcmp(argv[1], "tampered")) stop_on_map("m.nro");   /* FC26_RO_DIR names the directory with the bad image */
    else if (!strcmp(argv[1], "probe")) { ro_module_set_dir(dir); return ro_module_probe() ? 1 : 0; }
    else if (!strcmp(argv[1], "late")) { ro_module_set_dir(dir); test_late_slots(); }
    else if (!strcmp(argv[1], "late_missing")) { ro_module_set_dir(dir); test_late_missing(); }
    else return 2;
    if (failures) { fprintf(stderr, "%u checks failed\n", failures); return 1; }
    puts("ro service ok");
    return 0;
}
