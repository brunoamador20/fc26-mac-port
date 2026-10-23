#include "runtime.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>

/* Mock runtime tables with one late symbol */
static const LateSymbol late_symbols[] = {
    {"_ZN3nvn27pfncpp_nvnTextureReadTexelsE", "Engine.Render.Core2.PlatformNvn"},
    {NULL, NULL}
};

#define RUNTIME_MAX_LATE_SLOTS 128
static LateSlot late_slots[RUNTIME_MAX_LATE_SLOTS];
static unsigned late_slot_count;

static void need(bool c, const char *m) {
    if (!c) {
        fprintf(stderr, "need failed: %s\n", m);
        exit(1);
    }
}

static const char *find_late_symbol(const char *name) {
    for (const LateSymbol *ls = late_symbols; ls->name; ls++) {
        if (!strcmp(ls->name, name)) return ls->nro;
    }
    return NULL;
}

static void record_late_slot(void *slot, const char *name, const char *nro) {
    need(late_slot_count < RUNTIME_MAX_LATE_SLOTS, "too many late slots");
    late_slots[late_slot_count].slot = slot;
    late_slots[late_slot_count].name = name;
    late_slots[late_slot_count].nro = nro;
    late_slot_count++;
}

LateSlot *runtime_late_slots(unsigned *count) {
    if (count) *count = late_slot_count;
    return late_slots;
}

/* Stubs for runtime functions */
void *runtime_symbol(const char *name) { (void)name; return NULL; }
void *runtime_observer(const char *name) { (void)name; return NULL; }
void *runtime_override(const char *name) { (void)name; return NULL; }
void *runtime_hle_wrap_named(void *p, const char *name) { (void)name; return p; }
void runtime_missing(const char *format, ...) { (void)format; }
_Noreturn void runtime_fail(const char *message) {
    fprintf(stderr, "runtime_fail: %s\n", message);
    exit(42);
}

/* Identical relocation loop from loader.c */
static void relocate(Module *m) {
 for(unsigned i=0;i<m->nreloc;i++) {
  const Reloc *r=&m->relocs[i];
  need(r->where>=m->data_off&&r->where+8<=m->key_off&&r->symbol<m->nsym,"relocation bounds");
  uintptr_t v;
  if(r->kind==1027) { need(r->addend>=0&&(uint64_t)r->addend<m->key_off,"relative addend");v=(uintptr_t)m->base+r->addend;m->relative++; }
  else {
   need(r->kind==257||r->kind==1025||r->kind==1026,"relocation kind");
   const Symbol *s=&m->symbols[r->symbol];void *p=r->kind==1026&&runtime_symbol(s->name)?runtime_observer(s->name):NULL;
   if(!p)p=runtime_override(s->name);
   if(p)p=runtime_hle_wrap_named(p,s->name);
   if(!p)p=s->defined?(s->value<m->key_off?m->base+s->value:NULL):runtime_symbol(s->name);
   const char *late_nro=NULL;
   if(!p&&s->binding!=2){
    late_nro=find_late_symbol(s->name);
    if(!late_nro){fprintf(stderr,"%s unresolved %s\n",m->name,s->name);runtime_missing("import: %s needs %s",m->name,s->name);runtime_fail("strong import unresolved");}
    fprintf(stderr,"[rtld] Unresolved symbol: '%s' (late: exported by %s)\n",s->name,late_nro);
    record_late_slot(m->base+r->where,s->name,late_nro);
   }
   if(!p)m->weak++;
   if(p&&!s->defined)m->cross++;
   v=late_nro?0:((uintptr_t)p+(r->kind==1026?0:r->addend));m->symbolic++;
  }
  memcpy(m->base+r->where,&v,8);
 }
}

int main(int argc, char **argv) {
    if (argc < 2) return 1;
    uint8_t memory[0x40000];
    memset(memory, 0xaa, sizeof memory);
    
    if (!strcmp(argv[1], "test_late")) {
        Symbol syms[] = {
            {"", 0, 0, 0, 0, 0},
            {"_ZN3nvn27pfncpp_nvnTextureReadTexelsE", 0, 8, 0, 1, 1}
        };
        Reloc rels[] = {
            {0x21000, 1025, 1, 0}
        };
        Module m = {
            .name = "main",
            .data_off = 0x20000,
            .key_off = 0x30000,
            .base = memory,
            .symbols = syms,
            .nsym = 2,
            .relocs = rels,
            .nreloc = 1,
        };
        relocate(&m);
        uint64_t val;
        memcpy(&val, memory + 0x21000, 8);
        if (val != 0) {
            fprintf(stderr, "slot not 0: %#llx\n", (unsigned long long)val);
            return 2;
        }
        unsigned count = 0;
        LateSlot *slots = runtime_late_slots(&count);
        if (count != 1 || slots[0].slot != memory + 0x21000 ||
            strcmp(slots[0].name, "_ZN3nvn27pfncpp_nvnTextureReadTexelsE") != 0 ||
            strcmp(slots[0].nro, "Engine.Render.Core2.PlatformNvn") != 0) {
            fprintf(stderr, "late slots check failed: count=%u\n", count);
            return 3;
        }
        printf("LATE_OK\n");
        return 0;
    }
    
    if (!strcmp(argv[1], "test_unresolved")) {
        Symbol syms[] = {
            {"", 0, 0, 0, 0, 0},
            {"unexported_strong_symbol", 0, 8, 0, 1, 1}
        };
        Reloc rels[] = {
            {0x21000, 1025, 1, 0}
        };
        Module m = {
            .name = "main",
            .data_off = 0x20000,
            .key_off = 0x30000,
            .base = memory,
            .symbols = syms,
            .nsym = 2,
            .relocs = rels,
            .nreloc = 1,
        };
        relocate(&m);
        return 0;
    }
    
    return 1;
}
