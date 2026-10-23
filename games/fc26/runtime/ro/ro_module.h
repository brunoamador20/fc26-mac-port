/* nn::ro modules (NROs) on the host: the image rewritten ahead of time for the NRO's SHA-256 (nro_manifest.tsv), mapped
   at a new address with the rewriter's key page and host gates, protected the way loader.c protects main / subsdk0 /
   sdk. ro_service.c maps through here; loader.c and services.c reach loaded modules through the hooks at the end
   (games/fc26/docs/ESTORIA3_NUVEM.md, "Pontos de ligação"). */
#pragma once
#include "../runtime.h"
#include "ro_core.h"

/* Where the rewritten images and nro_manifest.tsv are: FC26_RO_DIR when set, else the directory given here (loader.c's
   main can pass argv[1]), else rewritten/v100 relative to the working directory (the Makefile runs from the work folder). */
void ro_module_set_dir(const char *dir);

/* Map the rewrite of the NRO the client handed over (nro: its bytes, checked and authorized by the caller; sha256: of
   those bytes). Returns 0 and the base address, or an ro result. Stops the runtime when no rewritten image is registered
   for this NRO or the image does not verify: a module the game is allowed to load but the host cannot run is a setup
   error, not something the game could recover from. The module is not relocated: on the console the game's own
   nn::ro library does that after the service returns (caminho A). */
uint32_t ro_module_map(const uint8_t *nro, const RoNro *header, const uint8_t sha256[32], uint64_t *base);
uint32_t ro_module_unmap(uint64_t base);

/* Caminho B, for when the game's nn::ro cannot link under the host (see the doc): relocate a mapped module with
   loader.c's resolution order (runtime_override wrapped by runtime_hle_wrap_named, the module's own definition,
   runtime_symbol). Once per module. 0, or -1 with the reason in err. */
int ro_module_link_host(uint64_t base, char *err, size_t errn);
void *ro_module_symbol(uint64_t base, const char *name);   /* a definition the module exports, NULL if none */

/* probe-ro (a loader.c mode, after the static modules are linked): each image in nro_manifest.tsv mapped as the service
   maps it, then every import looked up the way the host would link it (runtime_override, runtime_symbol). One JSON line
   per module on stdout; returns how many modules have a strong import that main / sdk do not export. */
int ro_module_probe(void);

/* Initialize the 5 nn::ro::detail globals exported by the sdk to point to host-owned storage: sentinels for
   g_pAutoLoadList / g_pManualLoadList, debug flag, and function pointer slots (Achado 2). */
void ro_module_init_sdk(void);

/* ---------- Hooks: each answers only for addresses inside a loaded module ---------- */
/* runtime_dispatch: handle a gate of a loaded module as loader.c handles its own (a timer gate writes the 19.2 MHz count,
   an svc gate goes to runtime_svc with the module's name and the svc's original offset). 0: not a module gate. */
int ro_module_dispatch(uint64_t ret, uint64_t *regs);
int ro_module_gate(uint64_t ret, Gate *gate, const char **name);   /* the gate itself, copied out */
/* svcSetMemoryPermission / svcSetMemoryAttribute / svcQueryMemory, with loader.c's results; RO_SVC_INVALID_MEMORY (0xd401)
   or 0 (query) when the address is not in a loaded module, so loader.c can return these in place of its own last line. */
uint64_t ro_module_permission(uint64_t address, uint64_t size, unsigned permission);
uint64_t ro_module_lock_permission(uint64_t address, uint64_t size, unsigned mask, unsigned attribute);
int ro_module_query(uint64_t address, uint64_t *base, uint64_t *size, unsigned *state, unsigned *permission, unsigned *attribute);
/* Diagnostics (runtime_describe_address, runtime_module_offset, the crash report): name and offset of an address. */
int ro_module_offset(uint64_t address, const char **name, uint64_t *offset);
uint64_t ro_module_bytes(void);   /* host memory the loaded images take (runtime_image_bytes) */
