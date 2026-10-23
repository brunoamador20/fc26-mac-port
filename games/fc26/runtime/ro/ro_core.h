/* nn::ro module loading without host calls (unit-tested on Linux by tests/test_fc26_ro_runtime.py):
   - NRR and NRO checks as the ro service makes them before it maps a module (switchbrew RO services / NRR0 / NRO0);
   - the rewritten image: patch_nso.py's layout (<name>.fixups.tsv), host gates (<name>.gates.tsv) and the catalog of
     rewritten images keyed by the NRO's SHA-256 (nro_manifest.tsv, written by scripts/nro_to_nso.py register);
   - page permissions: the guest's 4 KiB view (svcQueryMemory, svcSetMemoryPermission, RELRO lock) and the 16 KiB host
     pages that carry it, with the same union rule as loader.c;
   - the ELF dynamic section and a relocation pass for when the host links a module itself.
   runtime/ro/ro_module.c maps and protects with these; runtime/ro/ro_service.c answers ldr:ro / ro:1. */
#pragma once
#include <stddef.h>
#include <stdint.h>

#define RO_GUEST_PAGE 0x1000u        /* Horizon page: NRO segments, NRR buffers and svc permission ranges */
#define RO_HOST_PAGE 0x4000u         /* Apple silicon page: what mprotect works on */
#define RO_KEY_PAGE_SIZE 0x4000u
#define RO_KEY_SLOTS 8               /* patch_nso.py KEY_INDEX: K18 KTLS KTLR KGATE KRES0 KRES1 KASPECT KASPECTUI */
#define RO_MAX_NRR 0x40              /* per process, as the ro service */
#define RO_MAX_NRO 0x40
#define RO_NRR_HEADER_SIZE 0x350
#define RO_NRO_HEADER_SIZE 0x80
#define RO_MOD0_SIZE 0x1c

/* Results of module 22 (switchbrew "Error codes"; descriptions 5, 7, 10 and 11 as named by Atmosphère's ro). */
#define RO_RESULT(description) (22u | ((uint32_t)(description) << 9))
#define RO_OUT_OF_ADDRESS_SPACE RO_RESULT(2)
#define RO_ALREADY_LOADED RO_RESULT(3)
#define RO_INVALID_NRO RO_RESULT(4)
#define RO_NOT_FOUND RO_RESULT(5)
#define RO_INVALID_NRR RO_RESULT(6)
#define RO_TOO_MANY_NRO RO_RESULT(7)
#define RO_TOO_MANY_NRR RO_RESULT(8)
#define RO_NOT_AUTHORIZED RO_RESULT(9)
#define RO_INVALID_NRR_KIND RO_RESULT(10)
#define RO_INTERNAL_ERROR RO_RESULT(1023)
#define RO_INVALID_ADDRESS RO_RESULT(1025)
#define RO_INVALID_SIZE RO_RESULT(1026)
#define RO_NOT_LOADED RO_RESULT(1028)
#define RO_NOT_REGISTERED RO_RESULT(1029)
#define RO_INVALID_SESSION RO_RESULT(1030)
#define RO_INVALID_PROCESS RO_RESULT(1031)
/* Kernel results the svc paths return, the same values loader.c uses. */
#define RO_SVC_INVALID_ADDRESS 0xcc01u
#define RO_SVC_INVALID_SIZE 0xca01u
#define RO_SVC_INVALID_PERMISSION 0xd801u
#define RO_SVC_INVALID_MEMORY 0xd401u

enum { RO_NRR_USER = 0, RO_NRR_JIT_PLUGIN = 1 };
enum { RO_STATE_ALIAS_CODE = 8, RO_STATE_ALIAS_CODE_DATA = 9 };   /* switchbrew SVC MemoryType: MapProcessCodeMemory */
enum { RO_PROT_R = 1, RO_PROT_W = 2, RO_PROT_X = 4, RO_ATTR_PERMISSION_LOCKED = 16 };

/* ---------- NRR ---------- */
typedef struct { uint64_t program_id; uint32_t size, hash_offset, num_hashes; uint8_t kind; int sorted; const uint8_t *hashes; } RoNrr;
/* Structure of an NRR the client registered (size: the buffer it gave). Signatures are not checked: the host trusts the
   files it was given; every field the lookups use is bounds-checked. RO_INVALID_NRR / RO_INVALID_SIZE. */
uint32_t ro_nrr_parse(const uint8_t *nrr, uint64_t size, RoNrr *out);
/* program_id 0 skips that check; kind < 0 skips the NrrKind check. */
uint32_t ro_nrr_check(const RoNrr *nrr, uint64_t program_id, int kind);
/* Binary search, as the ro service does: the list has to be sorted (ro_nrr_parse reports whether it is). */
int ro_nrr_has(const uint8_t *hashes, uint32_t count, const uint8_t hash[32]);

/* ---------- NRO ---------- */
typedef struct { uint32_t size, flags, text_size, ro_off, ro_size, data_off, data_size, bss_size, mod0; uint8_t module_id[32]; } RoNro;
/* The header checks of MapManualLoadModuleMemory (nro_size / bss_size: what the client passed). RO_INVALID_NRO. */
uint32_t ro_nro_parse(const uint8_t *nro, uint64_t nro_size, uint64_t bss_size, RoNro *out);

/* ---------- Rewritten image ---------- */
typedef struct { uint64_t text_end, ro_off, data_off, key_off, patch_off, file_size; int key_index[RO_KEY_SLOTS]; } RoLayout;
typedef struct { uint64_t ret, original; unsigned timer, arg; } RoGate;   /* the fields of runtime.h's Gate */
typedef struct { uint8_t nro_sha256[32], image_sha256[32], module_id[32]; char name[64]; uint64_t nro_size, bss_size; } RoImage;
/* Each returns 0 on success, otherwise writes a reason into err. */
int ro_fixups_parse(const char *text, RoLayout *out, char *err, size_t errn);
int ro_layout_check(const RoLayout *l, const RoNro *nro, char *err, size_t errn);
int ro_gates_parse(const char *text, const RoLayout *l, RoGate **out, unsigned *count, char *err, size_t errn);   /* sorted by ret */
const RoGate *ro_gate_find(const RoGate *gates, unsigned count, uint64_t ret_offset);
/* 1 found, 0 no row for this hash, -1 malformed manifest (err says where). */
int ro_catalog_find(const char *text, const uint8_t nro_sha256[32], RoImage *out, char *err, size_t errn);
/* Every row in order; visit returns non-zero to stop the walk, which then returns that value; -1: malformed. */
int ro_catalog_each(const char *text, int (*visit)(void *ctx, const RoImage *row, unsigned line), void *ctx, char *err, size_t errn);

/* ---------- Host pages ---------- */
typedef struct { uint64_t off, size; unsigned prot; } RoRange;
uint64_t ro_map_size(const RoLayout *l);
/* The image's protections in 16 KiB pages (what loader.c's seal() gives a module): text r-x, rodata r--, data and bss
   rw-, key page r--, padding before the patch area ---, patch area r-x. Returns how many ranges (at most 6). */
unsigned ro_plan(const RoLayout *l, RoRange out[6]);

/* ---------- Guest view (4 KiB) ---------- */
typedef struct { uint64_t text_size, data_off, end, key_off; uint8_t *page; } RoGuestMemory;   /* end: NRO + bss */
int ro_guest_init(RoGuestMemory *g, const RoNro *nro, const RoLayout *l);   /* 0, or -1 when out of memory */
void ro_guest_free(RoGuestMemory *g);
/* svcSetMemoryPermission inside the module's data (perm 0, 1 or 3). On success [*lo, *hi) are the 16 KiB host pages to
   re-protect with ro_guest_host_prot. */
uint32_t ro_guest_set_permission(RoGuestMemory *g, uint64_t off, uint64_t size, unsigned perm, uint64_t *lo, uint64_t *hi);
uint32_t ro_guest_lock(RoGuestMemory *g, uint64_t off, uint64_t size, unsigned mask, unsigned attribute);
unsigned ro_guest_host_prot(const RoGuestMemory *g, uint64_t page_off);   /* union of the four guest pages */
/* svcQueryMemory for an offset below g->end: the run of pages around it with the same permission and state. */
void ro_guest_query(const RoGuestMemory *g, uint64_t off, uint64_t *base, uint64_t *size, unsigned *state, unsigned *perm, unsigned *attr);

/* ---------- ELF dynamic section ---------- */
typedef struct {
    uint64_t mod0, dynamic, symtab, strtab, strsz, hash, rela, relasz, jmprel, pltrelsz, relr, relrsz;
    uint64_t init, fini, init_array, init_arraysz; uint32_t nsym;
} RoDynamic;
typedef struct { const char *name; uint64_t value; unsigned type, binding, defined; } RoSymbol;
typedef struct { uint64_t where; int64_t addend; uint32_t type, symbol; } RoReloc;
int ro_dynamic_parse(const uint8_t *image, uint64_t size, RoDynamic *d, char *err, size_t errn);
int ro_symbol(const uint8_t *image, uint64_t size, const RoDynamic *d, uint32_t index, RoSymbol *out);
long ro_symbol_find(const uint8_t *image, uint64_t size, const RoDynamic *d, const char *name);   /* defined only */
/* RELR (type RELATIVE, implicit addend read from the image), then RELA, then JMPREL; targets must lie in [lo, hi - 8].
   visit returns non-zero to stop; the walk then returns that value. */
int ro_relocs_each(const uint8_t *image, uint64_t size, const RoDynamic *d, uint64_t lo, uint64_t hi,
                   int (*visit)(void *ctx, const RoReloc *r), void *ctx, char *err, size_t errn);

/* The host links a module itself (only when the game's own nn::ro does not: see docs/ESTORIA3_NUVEM.md, caminho B).
   resolve gives a symbol's address (defined: its address in this module, 0 for an import), NULL when unresolved;
   tlsdesc fills a TLSDESC pair or returns non-zero; without it a TLSDESC relocation is an error. */
typedef struct {
    void *ctx;
    void *(*resolve)(void *ctx, const RoSymbol *s, uint64_t defined);
    int (*tlsdesc)(void *ctx, const RoSymbol *s, int64_t addend, uint64_t pair[2]);
} RoLinker;
typedef struct { unsigned relative, symbolic, cross, weak_zero, tlsdesc; } RoLinkStats;
int ro_link(uint8_t *image, uint64_t size, uint64_t base, const RoDynamic *d, uint64_t lo, uint64_t hi,
            const RoLinker *linker, RoLinkStats *stats, char *err, size_t errn);
