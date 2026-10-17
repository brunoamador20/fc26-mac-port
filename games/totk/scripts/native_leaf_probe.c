/* Execute two verified, unchanged TOTK v0 ARM64 leaf functions on Apple silicon.
 * This is a loader probe, not a game launcher. No game entry/constructors run.
 */
#include <errno.h>
#include <inttypes.h>
#include <libkern/OSCacheControl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#if !defined(__APPLE__) || !defined(__aarch64__)
#error This probe requires an Apple silicon Mac.
#endif

typedef struct {
    unsigned char ident[16];
    uint16_t type, machine;
    uint32_t version;
    uint64_t entry, phoff, shoff;
    uint32_t flags;
    uint16_t ehsize, phentsize, phnum, shentsize, shnum, shstrndx;
} ElfHeader;
typedef struct {
    uint32_t type, flags;
    uint64_t offset, vaddr, paddr, filesz, memsz, align;
} ProgramHeader;
typedef struct { int64_t tag; uint64_t value; } Dynamic;
typedef struct { uint64_t offset, info; int64_t addend; } Rela;
_Static_assert(sizeof(ElfHeader) == 64, "ELF header layout");
_Static_assert(sizeof(ProgramHeader) == 56, "ELF program header layout");

static void need(int condition, const char *message) {
    if (!condition) { fprintf(stderr, "FAIL: %s\n", message); exit(1); }
}
static int within(uint64_t offset, uint64_t size, uint64_t limit) {
    return offset <= limit && size <= limit - offset;
}

int main(int argc, char **argv) {
    need(argc == 2, "usage: native_leaf_probe main.elf");
    FILE *file = fopen(argv[1], "rb");
    need(file != NULL, "open ELF");
    need(fseek(file, 0, SEEK_END) == 0, "seek ELF");
    long file_size = ftell(file);
    need(file_size >= 64 && file_size <= 128 * 1024 * 1024, "ELF file size");
    rewind(file);
    unsigned char *bytes = malloc((size_t)file_size);
    need(bytes != NULL, "allocate file buffer");
    need(fread(bytes, 1, (size_t)file_size, file) == (size_t)file_size, "read ELF");
    fclose(file);
    ElfHeader header;
    memcpy(&header, bytes, sizeof(header));
    need(memcmp(header.ident, "\177ELF\2\1\1", 7) == 0 && header.machine == 183,
         "expected little-endian AArch64 ELF64");
    need(header.phentsize == 56 && header.phnum > 0 && header.phnum <= 16,
         "program-header layout");
    need(within(header.phoff, (uint64_t)header.phnum * 56, (uint64_t)file_size),
         "program-header bounds");
    ProgramHeader programs[16];
    memcpy(programs, bytes + header.phoff, (size_t)header.phnum * 56);
    uint64_t image_size = 0, text_size = 0, dynamic_offset = 0, dynamic_size = 0;
    for (unsigned i = 0; i < header.phnum; ++i) {
        ProgramHeader *p = &programs[i];
        if (p->type == 1) {
            need(p->filesz <= p->memsz && within(p->offset, p->filesz, (uint64_t)file_size),
                 "LOAD file bounds");
            need(within(p->vaddr, p->memsz, 256 * 1024 * 1024), "LOAD memory bounds");
            if (image_size < p->vaddr + p->memsz) image_size = p->vaddr + p->memsz;
            if (p->flags & 1) {
                need(p->vaddr == 0 && text_size == 0, "single zero-based text LOAD");
                text_size = p->filesz;
            }
        } else if (p->type == 2) {
            dynamic_offset = p->vaddr; dynamic_size = p->filesz;
        }
    }
    need(text_size > 0x410 && image_size > 0x4540468, "expected TOTK v0 layout");
    size_t page_size = (size_t)sysconf(_SC_PAGESIZE);
    size_t mapping_size = ((size_t)image_size + page_size - 1) & ~(page_size - 1);
    unsigned char *base = mmap(NULL, mapping_size, PROT_READ | PROT_WRITE,
                              MAP_PRIVATE | MAP_ANON, -1, 0);
    need(base != MAP_FAILED, "allocate guest memory");
    for (unsigned i = 0; i < header.phnum; ++i) {
        ProgramHeader *p = &programs[i];
        if (p->type == 1) memcpy(base + p->vaddr, bytes + p->offset, (size_t)p->filesz);
    }
    free(bytes);
    need(within(dynamic_offset, dynamic_size, image_size) && dynamic_size % 16 == 0,
         "dynamic table bounds");
    uint64_t rela_offset = 0, rela_size = 0;
    for (uint64_t i = 0; i < dynamic_size; i += 16) {
        Dynamic item;
        memcpy(&item, base + dynamic_offset + i, 16);
        if (item.tag == 7) rela_offset = item.value;
        if (item.tag == 8) rela_size = item.value;
        if (item.tag == 0) break;
    }
    need(rela_size % 24 == 0 && within(rela_offset, rela_size, image_size), "RELA table bounds");
    unsigned relative_count = 0;
    for (uint64_t i = 0; i < rela_size; i += 24) {
        Rela rela;
        memcpy(&rela, base + rela_offset + i, 24);
        if ((uint32_t)rela.info != 1027) continue; /* R_AARCH64_RELATIVE only. */
        need(within(rela.offset, 8, image_size) && rela.offset >= text_size,
             "relative relocation target");
        need(rela.addend >= 0 && (uint64_t)rela.addend <= image_size, "relative relocation addend");
        uint64_t value = (uint64_t)(uintptr_t)base + (uint64_t)rela.addend;
        memcpy(base + rela.offset, &value, 8);
        ++relative_count;
    }
    const unsigned char expected_start[12] = {0x00,0x2a,0x02,0x90,0x00,0x2c,0x42,0xf9,0xc0,0x03,0x5f,0xd6};
    const unsigned char expected_end[12] = {0x00,0x2a,0x02,0x90,0x00,0x30,0x42,0xf9,0xc0,0x03,0x5f,0xd6};
    need(memcmp(base + 0x3f0, expected_start, 12) == 0 &&
         memcmp(base + 0x400, expected_end, 12) == 0, "leaf instructions differ from verified TOTK v0 bytes");
    uint64_t start_slot, end_slot;
    memcpy(&start_slot, base + 0x4540458, 8);
    memcpy(&end_slot, base + 0x4540460, 8);
    need(start_slot == (uintptr_t)base + 0x3640ca0 &&
         end_slot == (uintptr_t)base + 0x37dd50a, "expected leaf GOT relocations");
    size_t executable_size = ((size_t)text_size + page_size - 1) & ~(page_size - 1);
    sys_icache_invalidate(base, (size_t)text_size);
    if (mprotect(base, executable_size, PROT_READ | PROT_EXEC) != 0) {
        fprintf(stderr, "mprotect: %s\n", strerror(errno));
        munmap(base, mapping_size); return 1;
    }
    typedef uintptr_t (*Getter)(void);
    uintptr_t actual_start = ((Getter)(void *)(base + 0x3f0))();
    uintptr_t actual_end = ((Getter)(void *)(base + 0x400))();
    need(actual_start == start_slot && actual_end == end_slot, "native return values mismatch");
    printf("{\"status\":\"pass\",\"execution\":\"original AArch64 instructions on Apple silicon\","
           "\"functions\":[\"nndetailRoGetRoDataStart\",\"nndetailRoGetRoDataEnd\"],"
           "\"relative_relocations\":%u,\"returned_module_offsets\":[%" PRIuPTR ",%" PRIuPTR "],"
           "\"scope\":\"two leaf functions only; game entry not executed\"}\n",
           relative_count, actual_start - (uintptr_t)base, actual_end - (uintptr_t)base);
    munmap(base, mapping_size);
    return 0;
}
