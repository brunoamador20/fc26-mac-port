/* See ro_module.h. Mapping follows loader.c's map_module / seal for the Mac (not the iOS embedding path). */
#include "ro_module.h"
#include "ro_sha256.h"
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#if defined(__APPLE__)
#include <TargetConditionals.h>
#include <libkern/OSCacheControl.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>
#else
#include <unistd.h>
#endif

typedef struct {
    uint8_t *base; uint64_t map_size; char name[64]; uint8_t sha256[32];
    RoNro nro; RoLayout layout; RoDynamic dynamic; RoGate *gates; unsigned ngates;
    RoGuestMemory guest; int linked;
} Loaded;

static Loaded *loaded[RO_MAX_NRO];   /* written under the lock; the crash path reads it without one */
static pthread_rwlock_t lock = PTHREAD_RWLOCK_INITIALIZER;
static char given_dir[4096];

void ro_module_set_dir(const char *dir) { snprintf(given_dir, sizeof given_dir, "%s", dir ? dir : ""); }

static const char *image_dir(void) {
    const char *env = getenv("FC26_RO_DIR");
    return env && *env ? env : given_dir[0] ? given_dir : "rewritten/v100";
}

static _Noreturn void setup_error(const char *what, const char *detail) {
    fprintf(stderr, "[fc26-ro] %s: %s\n", what, detail);
    runtime_fail("nn::ro module image (games/fc26/docs/ESTORIA3_NUVEM.md, Integração no Mac)");
}

/* A whole file into memory (text files get a terminating zero). */
static uint8_t *read_file(const char *name, const char *suffix, size_t *size) {
    char path[4200]; snprintf(path, sizeof path, "%s/%s%s", image_dir(), name, suffix);
    FILE *f = fopen(path, "rb");
    if (!f) setup_error("cannot open", path);
    if (fseek(f, 0, SEEK_END) || ftell(f) < 0) setup_error("cannot size", path);
    size_t n = (size_t)ftell(f); rewind(f);
    uint8_t *p = malloc(n + 1);
    if (!p || fread(p, 1, n, f) != n) setup_error("cannot read", path);
    fclose(f); p[n] = 0; *size = n;
    return p;
}

static int to_prot(unsigned prot) {
    return (prot & RO_PROT_R ? PROT_READ : 0) | (prot & RO_PROT_W ? PROT_WRITE : 0) | (prot & RO_PROT_X ? PROT_EXEC : 0);
}

static void flush_code(uint8_t *p, uint64_t n) {
    if (!n) return;
#if defined(__APPLE__)
    sys_icache_invalidate(p, (size_t)n);
#else
    __builtin___clear_cache((char *)p, (char *)p + n);
#endif
}

/* A 16 KiB aligned anonymous read-write range (Darwin's pages are 16 KiB; other hosts get it aligned by trimming). */
static uint8_t *reserve(uint64_t size) {
    uint8_t *p = mmap(NULL, (size_t)(size + RO_HOST_PAGE), PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
    if (p == MAP_FAILED) return NULL;
    uint8_t *aligned = (uint8_t *)(((uintptr_t)p + RO_HOST_PAGE - 1) & ~(uintptr_t)(RO_HOST_PAGE - 1));
    if (aligned > p) munmap(p, (size_t)(aligned - p));
    if (aligned + size < p + size + RO_HOST_PAGE) munmap(aligned + size, (size_t)(p + size + RO_HOST_PAGE - (aligned + size)));
    return aligned;
}

static void release(Loaded *m) {
    if (m->base) munmap(m->base, (size_t)m->map_size);
    ro_guest_free(&m->guest); free(m->gates); free(m);
}

static void write_slot(void *slot, uintptr_t val) {
#if defined(__APPLE__)
    mach_vm_address_t a = (mach_vm_address_t)(uintptr_t)slot;
    mach_vm_size_t size = 0;
    vm_region_basic_info_data_64_t info;
    mach_msg_type_number_t count = VM_REGION_BASIC_INFO_COUNT_64;
    mach_port_t object = MACH_PORT_NULL;
    kern_return_t kr = mach_vm_region(mach_task_self(), &a, &size, VM_REGION_BASIC_INFO_64, (vm_region_info_t)&info, &count, &object);
    if (object) mach_port_deallocate(mach_task_self(), object);
    if (kr != KERN_SUCCESS) runtime_fail("mach_vm_region for late slot");
    vm_prot_t orig = info.protection;
    if (!(orig & VM_PROT_WRITE)) {
        uintptr_t page = (uintptr_t)slot & ~(uintptr_t)0x3fff;
        if (mprotect((void *)page, 0x4000, PROT_READ | PROT_WRITE) != 0) runtime_fail("mprotect RW for late slot");
        *(uintptr_t *)slot = val;
        if (mprotect((void *)page, 0x4000, (int)orig) != 0) runtime_fail("mprotect restore for late slot");
    } else {
        *(uintptr_t *)slot = val;
    }
#else
    FILE *f = fopen("/proc/self/maps", "r");
    int prot = 3;
    if (f) {
        char line[512];
        uintptr_t addr = (uintptr_t)slot;
        while (fgets(line, sizeof line, f)) {
            unsigned long long lo, hi; char perms[8];
            if (sscanf(line, "%llx-%llx %7s", &lo, &hi, perms) == 3 && addr >= lo && addr < hi) {
                prot = (perms[0] == 'r' ? 1 : 0) | (perms[1] == 'w' ? 2 : 0) | (perms[2] == 'x' ? 4 : 0);
                break;
            }
        }
        fclose(f);
    }
    if (!(prot & 2)) {
        long pagesize = sysconf(_SC_PAGESIZE);
        if (pagesize <= 0) pagesize = 4096;
        uintptr_t page = (uintptr_t)slot & ~(uintptr_t)(pagesize - 1);
        int orig_prot = (prot & 1 ? PROT_READ : 0) | (prot & 4 ? PROT_EXEC : 0);
        if (mprotect((void *)page, (size_t)pagesize, PROT_READ | PROT_WRITE) != 0) runtime_fail("mprotect RW for late slot");
        *(uintptr_t *)slot = val;
        if (mprotect((void *)page, (size_t)pagesize, orig_prot) != 0) runtime_fail("mprotect restore for late slot");
    } else {
        *(uintptr_t *)slot = val;
    }
#endif
}

static int nro_matches(const char *slot_nro, const char *module_name) {
    if (!slot_nro || !module_name) return 0;
    if (!strcmp(slot_nro, module_name)) return 1;
    const char *dot = strrchr(slot_nro, '.');
    if (dot && !strcmp(dot + 1, module_name)) return 1;
    dot = strrchr(module_name, '.');
    if (dot && !strcmp(dot + 1, slot_nro)) return 1;
    return 0;
}

static void ro_late_slots_relink(Loaded *m) {
    unsigned count = 0;
    LateSlot *slots = runtime_late_slots(&count);
    if (!slots || !count) return;
    uint64_t end = (uint64_t)m->nro.size + m->nro.bss_size;
    unsigned relinked = 0;
    for (unsigned i = 0; i < count; i++) {
        if (!nro_matches(slots[i].nro, m->name)) continue;
        long idx = ro_symbol_find(m->base, end, &m->dynamic, slots[i].name);
        RoSymbol s;
        if (idx < 0 || ro_symbol(m->base, end, &m->dynamic, (uint32_t)idx, &s) || !s.defined) {
            runtime_missing("late slot: module %s does not export %s", m->name, slots[i].name);
            runtime_fail("late slot symbol missing");
        }
        uintptr_t target = (uintptr_t)m->base + s.value;
        write_slot(slots[i].slot, target);
        fprintf(stderr, "[fc26-ro] late slot %s -> %s+0x%llx\n", slots[i].name, m->name, (unsigned long long)s.value);
        relinked++;
    }
    if (relinked > 0) {
        fprintf(stderr, "[fc26-ro] %u late slots relinked for %s\n", relinked, m->name);
    }
}

static void ro_late_slots_unlink(const char *name) {
    unsigned count = 0;
    LateSlot *slots = runtime_late_slots(&count);
    if (!slots || !count) return;
    unsigned cleared = 0;
    for (unsigned i = 0; i < count; i++) {
        if (!nro_matches(slots[i].nro, name)) continue;
        write_slot(slots[i].slot, 0);
        cleared++;
    }
    if (cleared > 0) {
        fprintf(stderr, "[fc26-ro] %u late slots cleared for %s\n", cleared, name);
    }
}

uint32_t ro_module_map(const uint8_t *nro, const RoNro *header, const uint8_t sha256[32], uint64_t *base) {
#if defined(TARGET_OS_IPHONE) && TARGET_OS_IPHONE
    runtime_fail("nn::ro modules on iOS need their code embedded like the static modules (not done)");
#endif
    char err[256], hex[65], id[65];
    ro_hex(sha256, 32, hex); ro_hex(header->module_id, 32, id);
    size_t size; char *manifest = (char *)read_file("nro_manifest.tsv", "", &size);
    RoImage row;
    int found = ro_catalog_find(manifest, sha256, &row, err, sizeof err);
    free(manifest);
    if (found < 0) setup_error("nro_manifest.tsv", err);
    if (!found) {
        fprintf(stderr, "[fc26-ro] the game loads NRO sha256=%s module_id=%s, which has no rewritten image in %s: run "
                "scripts/nro_to_nso.py wrap, third_party/d2r/patch_nso.py and nro_to_nso.py register for it\n", hex, id, image_dir());
        runtime_fail("nn::ro module without a rewritten image");
    }
    if (row.nro_size != header->size || row.bss_size != header->bss_size || memcmp(row.module_id, header->module_id, 32))
        setup_error("nro_manifest.tsv row disagrees with the NRO header", row.name);
    (void)nro;   /* the bytes were hashed by the caller; the image below is the verified rewrite of exactly those bytes */

    Loaded *m = calloc(1, sizeof *m);
    if (!m) runtime_fail("nn::ro module allocation");
    memcpy(m->name, row.name, sizeof m->name); memcpy(m->sha256, sha256, 32); m->nro = *header;
    char *fixups = (char *)read_file(row.name, ".fixups.tsv", &size);
    if (ro_fixups_parse(fixups, &m->layout, err, sizeof err)) setup_error(row.name, err);
    free(fixups);
    uint8_t *image = read_file(row.name, ".patched.bin", &size);
    m->layout.file_size = size;
    if (ro_layout_check(&m->layout, header, err, sizeof err)) setup_error(row.name, err);
    uint8_t digest[32];
    ro_sha256(image, size, digest);
    if (memcmp(digest, row.image_sha256, 32)) setup_error("rewritten image SHA-256 differs from nro_manifest.tsv", row.name);
    char *gates = (char *)read_file(row.name, ".gates.tsv", &size);
    if (ro_gates_parse(gates, &m->layout, &m->gates, &m->ngates, err, sizeof err)) setup_error(row.name, err);
    free(gates);

    m->map_size = ro_map_size(&m->layout);
    m->base = reserve(m->map_size);
    if (!m->base) { free(image); release(m); return RO_OUT_OF_ADDRESS_SPACE; }
    memcpy(m->base, image, (size_t)m->layout.file_size);
    free(image);
    if (ro_dynamic_parse(m->base, (uint64_t)header->size + header->bss_size, &m->dynamic, err, sizeof err)) setup_error(row.name, err);
    /* Key page: slot i's Darwin TSD offset at index i, as loader.c writes it for every module (fixups.tsv agreed). */
    uint64_t *key = (uint64_t *)(m->base + m->layout.key_off);
    for (unsigned i = 0; i < RO_KEY_SLOTS; i++) key[i] = (uint64_t)runtime_keys[i] * 8;
    if (ro_guest_init(&m->guest, header, &m->layout)) runtime_fail("nn::ro module permission table");
    RoRange ranges[6];
    unsigned n = ro_plan(&m->layout, ranges);
    for (unsigned i = 0; i < n; i++)
        if (mprotect(m->base + ranges[i].off, (size_t)ranges[i].size, to_prot(ranges[i].prot))) setup_error("mprotect", row.name);
    flush_code(m->base, ranges[0].size);
    if (ranges[n - 1].prot & RO_PROT_X) flush_code(m->base + ranges[n - 1].off, ranges[n - 1].size);

    pthread_rwlock_wrlock(&lock);
    unsigned slot = 0;
    while (slot < RO_MAX_NRO && loaded[slot]) slot++;
    if (slot == RO_MAX_NRO) { pthread_rwlock_unlock(&lock); release(m); return RO_TOO_MANY_NRO; }
    __atomic_store_n(&loaded[slot], m, __ATOMIC_RELEASE);
    pthread_rwlock_unlock(&lock);
    fprintf(stderr, "[fc26-ro] mapped %s at %p size=%#llx gates=%u nro=%s\n", m->name, (void *)m->base,
            (unsigned long long)m->map_size, m->ngates, hex);
    ro_late_slots_relink(m);
    *base = (uint64_t)(uintptr_t)m->base;
    return 0;
}

uint32_t ro_module_unmap(uint64_t base) {
    pthread_rwlock_wrlock(&lock);
    for (unsigned i = 0; i < RO_MAX_NRO; i++) {
        Loaded *m = loaded[i];
        if (!m || (uint64_t)(uintptr_t)m->base != base) continue;
        __atomic_store_n(&loaded[i], NULL, __ATOMIC_RELEASE);
        pthread_rwlock_unlock(&lock);
        fprintf(stderr, "[fc26-ro] unmapped %s at %p\n", m->name, (void *)m->base);
        ro_late_slots_unlink(m->name);
        release(m);
        return 0;
    }
    pthread_rwlock_unlock(&lock);
    return RO_NOT_LOADED;
}

/* The loaded module containing [address, address + size); call with the lock held. */
static Loaded *containing(uint64_t address, uint64_t size) {
    for (unsigned i = 0; i < RO_MAX_NRO; i++) {
        Loaded *m = loaded[i];
        uint64_t start = m ? (uint64_t)(uintptr_t)m->base : 0;
        if (m && address >= start && address - start < m->map_size && size <= m->map_size - (address - start)) return m;
    }
    return NULL;
}

static void *host_resolve(void *ctx, const RoSymbol *s, uint64_t defined) {
    (void)ctx;
    void *p = runtime_override(s->name);
    if (p) return runtime_hle_wrap_named(p, s->name);   /* host replacements run on the thread's host stack */
    if (s->defined) return (void *)(uintptr_t)defined;
    return runtime_symbol(s->name);
}

int ro_module_link_host(uint64_t base, char *err, size_t errn) {
    pthread_rwlock_wrlock(&lock);
    Loaded *m = containing(base, 1);
    int r = -1;
    if (!m || (uint64_t)(uintptr_t)m->base != base) snprintf(err, errn, "no module at %#llx", (unsigned long long)base);
    else if (m->linked) snprintf(err, errn, "%s is linked already", m->name);
    else {
        RoLinker linker = {NULL, host_resolve, NULL};   /* no TLS model for modules yet: TLSDESC stops the link */
        RoLinkStats st;
        uint64_t end = (uint64_t)m->nro.size + m->nro.bss_size;
        r = ro_link(m->base, end, base, &m->dynamic, m->nro.data_off, end, &linker, &st, err, errn);
        m->linked = !r;
        if (!r) fprintf(stderr, "[fc26-ro] %s linked by the host: relative=%u symbolic=%u cross=%u weak_zero=%u\n",
                        m->name, st.relative, st.symbolic, st.cross, st.weak_zero);
    }
    pthread_rwlock_unlock(&lock);
    return r;
}

void *ro_module_symbol(uint64_t base, const char *name) {
    pthread_rwlock_rdlock(&lock);
    Loaded *m = containing(base, 1);
    void *p = NULL;
    if (m && (uint64_t)(uintptr_t)m->base == base) {
        long i = ro_symbol_find(m->base, (uint64_t)m->nro.size + m->nro.bss_size, &m->dynamic, name);
        RoSymbol s;
        if (i >= 0 && !ro_symbol(m->base, (uint64_t)m->nro.size + m->nro.bss_size, &m->dynamic, (uint32_t)i, &s)) p = m->base + s.value;
    }
    pthread_rwlock_unlock(&lock);
    return p;
}

int ro_module_gate(uint64_t ret, Gate *gate, const char **name) {
    pthread_rwlock_rdlock(&lock);
    Loaded *m = containing(ret, 0);
    const RoGate *g = m ? ro_gate_find(m->gates, m->ngates, ret - (uint64_t)(uintptr_t)m->base) : NULL;
    if (g) { *gate = (Gate){g->ret, g->original, g->timer, g->arg}; *name = m->name; }
    pthread_rwlock_unlock(&lock);
    return g != NULL;
}

int ro_module_dispatch(uint64_t ret, uint64_t *regs) {
    Gate g; const char *name;
    if (!ro_module_gate(ret, &g, &name)) return 0;
    if (g.timer) {   /* the Switch counter runs at 19.2 MHz: ns * 12 / 625, as loader.c */
        if (g.arg >= 31 || g.arg == 18) runtime_fail("timer target register");
        regs[g.arg] = (uint64_t)((__uint128_t)runtime_now_ns() * 12 / 625);
        return 1;
    }
    runtime_svc(g.arg, regs, name, g.original);
    return 1;
}

typedef struct {
    const Loaded *m; uint8_t *seen; unsigned imports, overridden, missing, weak_missing, tlsdesc, relative, symbolic;
    char lists[4][4096]; size_t used[4];   /* overridden, missing, weak_missing, tlsdesc names (JSON arrays) */
} Probe;

static void probe_add(Probe *p, unsigned list, const char *name) {
    char item[300]; size_t n = 0;
    item[n++] = '"';
    for (const char *c = name; *c && n < sizeof item - 4; c++) { if (*c == '"' || *c == '\\') item[n++] = '\\'; item[n++] = *c; }
    item[n++] = '"'; item[n] = 0;
    int w = snprintf(p->lists[list] + p->used[list], sizeof p->lists[list] - p->used[list], "%s%s", p->used[list] ? "," : "", item);
    if (w > 0 && (size_t)w < sizeof p->lists[list] - p->used[list]) p->used[list] += (size_t)w;
    else p->lists[list][p->used[list]] = '\0';
}

static int probe_reloc(void *ctx, const RoReloc *r) {
    Probe *p = ctx;
    const Loaded *m = p->m;
    uint64_t size = (uint64_t)m->nro.size + m->nro.bss_size;
    RoSymbol s = {"", 0, 0, 0, 0};
    if (r->symbol && ro_symbol(m->base, size, &m->dynamic, r->symbol, &s)) return -1;
    if (r->type == 1027) { p->relative++; return 0; }
    if (r->type == 1031) { p->tlsdesc++; probe_add(p, 3, s.name[0] ? s.name : "(local)"); return 0; }
    p->symbolic++;
    if (!r->symbol || s.defined || (p->seen[r->symbol / 8] & (1u << (r->symbol % 8)))) return 0;
    p->seen[r->symbol / 8] |= (uint8_t)(1u << (r->symbol % 8));   /* each import once, however many slots use it */
    p->imports++;
    int overridden = runtime_override(s.name) != NULL;
    if (overridden) { p->overridden++; probe_add(p, 0, s.name); }
    if (!overridden && !runtime_symbol(s.name)) {
        if (s.binding == 2) { p->weak_missing++; probe_add(p, 2, s.name); }
        else { p->missing++; probe_add(p, 1, s.name); }
    }
    return 0;
}

static int probe_row(void *ctx, const RoImage *row, unsigned line) {
    (void)line;
    unsigned *failed = ctx;
    size_t size; uint8_t *image = read_file(row->name, ".patched.bin", &size);
    RoNro header;   /* the NRO header and MOD0 are in the image unchanged (nro_to_nso.py register checked) */
    if (size < row->nro_size || ro_nro_parse(image, row->nro_size, row->bss_size, &header)) setup_error("probe: NRO header in the image", row->name);
    uint64_t base;
    uint32_t r = ro_module_map(image, &header, row->nro_sha256, &base);
    free(image);
    if (r) { printf("{\"status\":\"fail\",\"module\":\"%s\",\"map_result\":\"%#x\"}\n", row->name, r); (*failed)++; return 0; }
    pthread_rwlock_rdlock(&lock);
    Loaded *m = containing(base, 1);
    Probe *p = calloc(1, sizeof *p);
    if (!p || !(p->seen = calloc(m->dynamic.nsym / 8 + 1, 1))) runtime_fail("probe allocation");
    p->m = m;
    char err[256];
    if (ro_relocs_each(m->base, (uint64_t)m->nro.size + m->nro.bss_size, &m->dynamic, m->nro.data_off,
                       (uint64_t)m->nro.size + m->nro.bss_size, probe_reloc, p, err, sizeof err)) setup_error(row->name, err);
    unsigned gates = m->ngates;
    pthread_rwlock_unlock(&lock);
    printf("{\"status\":\"%s\",\"module\":\"%s\",\"base\":\"%#llx\",\"gates\":%u,\"relative\":%u,\"symbolic\":%u,\"imports\":%u,"
           "\"overridden\":[%s],\"missing\":[%s],\"weak_missing\":[%s],\"tlsdesc\":[%s],\"scope\":\"image mapped and protected; "
           "imports looked up as the host would link them; the module was not relocated or run\"}\n",
           p->missing ? "fail" : "pass", row->name, (unsigned long long)base, gates, p->relative, p->symbolic, p->imports,
           p->lists[0], p->lists[1], p->lists[2], p->lists[3]);
    fflush(stdout);
    if (p->missing) (*failed)++;
    free(p->seen); free(p);
    ro_module_unmap(base);
    return 0;
}

int ro_module_probe(void) {
    size_t size; char *manifest = (char *)read_file("nro_manifest.tsv", "", &size), err[256];
    unsigned failed = 0;
    if (ro_catalog_each(manifest, probe_row, &failed, err, sizeof err)) setup_error("nro_manifest.tsv", err);
    free(manifest);
    return (int)failed;
}

/* nn::ro::detail globals in sdk exported by the Horizon SDK (Achado 2).
   In the console rtld initializes these before main. On MacNativeGames, loader.c
   does not run rtld, so the host initializes them after static modules are mapped. */
typedef struct RoListEntry {
    struct RoListEntry *next;
    struct RoListEntry *prev;
} RoListEntry;

static RoListEntry s_auto_list = { &s_auto_list, &s_auto_list };
static RoListEntry s_manual_list = { &s_manual_list, &s_manual_list };
static uint8_t s_ro_debug_flag = 0;
static void *s_lookup_manual_fn = NULL;
static void *s_lookup_auto_fn = NULL;

static void *ro_lookup_global_auto(const char *name) {
    if (!name) return NULL;
    void *p = runtime_override(name);
    if (p) return runtime_hle_wrap_named(p, name);
    return runtime_symbol(name);
}

void ro_module_init_sdk(void) {
    RoListEntry **p_auto = (RoListEntry **)runtime_symbol("_ZN2nn2ro6detail15g_pAutoLoadListE");
    RoListEntry **p_manual = (RoListEntry **)runtime_symbol("_ZN2nn2ro6detail17g_pManualLoadListE");
    void **p_lookup_auto = (void **)runtime_symbol("_ZN2nn2ro6detail34g_pLookupGlobalAutoFunctionPointerE");
    void ***p_lookup_manual = (void ***)runtime_symbol("_ZN2nn2ro6detail36g_pLookupGlobalManualFunctionPointerE");
    uint8_t **p_debug = (uint8_t **)runtime_symbol("_ZN2nn2ro6detail14g_pRoDebugFlagE");

    if (p_auto) *p_auto = &s_auto_list;
    if (p_manual) *p_manual = &s_manual_list;
    if (p_debug) *p_debug = &s_ro_debug_flag;
    if (p_lookup_manual) *p_lookup_manual = &s_lookup_manual_fn;   /* a cell the sdk stores its LookupGlobalManual into (sdk+0x149fd0) */
    if (p_lookup_auto) {
        if (!s_lookup_auto_fn)
            s_lookup_auto_fn = runtime_hle_wrap_named((void *)ro_lookup_global_auto, "ro_lookup_global_auto");
        *p_lookup_auto = s_lookup_auto_fn;   /* called directly (sdk+0x14ab34/0x14c62c: ldr x8, [x8]; blr x8) */
    }
}

/* Guest permission changes land on whole 16 KiB host pages: each gets the union of its four guest pages (loader.c). */
static void apply(Loaded *m, uint64_t lo, uint64_t hi) {
    for (uint64_t page = lo; page < hi; page += RO_HOST_PAGE) {
        unsigned prot = ro_guest_host_prot(&m->guest, page);
        if (prot & RO_PROT_X) runtime_fail("nn::ro module permission overlaps an executable page");
        if (mprotect(m->base + page, RO_HOST_PAGE, to_prot(prot))) runtime_fail("nn::ro module data permission");
    }
}

uint64_t ro_module_permission(uint64_t address, uint64_t size, unsigned permission) {
    pthread_rwlock_wrlock(&lock);
    Loaded *m = containing(address, size);
    uint64_t r = RO_SVC_INVALID_MEMORY, lo, hi;
    if (m) {
        uint64_t off = address - (uint64_t)(uintptr_t)m->base;
        r = ro_guest_set_permission(&m->guest, off, size, permission, &lo, &hi);
        if (!r) {
            apply(m, lo, hi);
            fprintf(stderr, "[fc26-ro] %s data permission +%#llx size=%#llx perm=%u\n", m->name, (unsigned long long)off, (unsigned long long)size, permission);
        }
    }
    pthread_rwlock_unlock(&lock);
    return r;
}

uint64_t ro_module_lock_permission(uint64_t address, uint64_t size, unsigned mask, unsigned attribute) {
    pthread_rwlock_wrlock(&lock);
    Loaded *m = containing(address, size);
    uint64_t r = m ? ro_guest_lock(&m->guest, address - (uint64_t)(uintptr_t)m->base, size, mask, attribute) : RO_SVC_INVALID_MEMORY;
    pthread_rwlock_unlock(&lock);
    return r;
}

int ro_module_query(uint64_t address, uint64_t *base, uint64_t *size, unsigned *state, unsigned *permission, unsigned *attribute) {
    pthread_rwlock_rdlock(&lock);
    Loaded *m = containing(address, 0);
    /* Only the module as the console has it (NRO + bss); the key page and patch area are host additions. */
    int r = m && address - (uint64_t)(uintptr_t)m->base < m->guest.end;
    if (r) {
        ro_guest_query(&m->guest, address - (uint64_t)(uintptr_t)m->base, base, size, state, permission, attribute);
        *base += (uint64_t)(uintptr_t)m->base;
    }
    pthread_rwlock_unlock(&lock);
    return r;
}

int ro_module_offset(uint64_t address, const char **name, uint64_t *offset) {
    for (unsigned i = 0; i < RO_MAX_NRO; i++) {   /* no lock: also used from the crash report */
        Loaded *m = __atomic_load_n(&loaded[i], __ATOMIC_ACQUIRE);
        if (m && address - (uint64_t)(uintptr_t)m->base < m->map_size) { *name = m->name; *offset = address - (uint64_t)(uintptr_t)m->base; return 1; }
    }
    return 0;
}

uint64_t ro_module_bytes(void) {
    uint64_t total = 0;
    pthread_rwlock_rdlock(&lock);
    for (unsigned i = 0; i < RO_MAX_NRO; i++) if (loaded[i]) total += loaded[i]->map_size;
    pthread_rwlock_unlock(&lock);
    return total;
}

size_t ro_module_regions(MemoryRegion *out, size_t max_count) {
    size_t n = 0;
    pthread_rwlock_rdlock(&lock);
    for (unsigned i = 0; i < RO_MAX_NRO && n < max_count; i++) {
        Loaded *m = loaded[i];
        if (m && m->base) {
            out[n].start = (uint64_t)(uintptr_t)m->base;
            out[n].end = (uint64_t)(uintptr_t)m->base + m->map_size;
            n++;
        }
    }
    pthread_rwlock_unlock(&lock);
    return n;
}
