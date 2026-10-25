#include "../runtime/game_patches.c"
#include <assert.h>
#include <sys/mman.h>
_Noreturn void runtime_fail(const char *s) { fprintf(stderr, "%s\n", s); exit(42); }
int main(int argc, char **argv) {
    (void)argc;
    size_t len = 0x58ab100;
    uint8_t *data = mmap(NULL, len, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANON, -1, 0);
    assert(data != MAP_FAILED);
    memset(data + 0x58ab0e4, 0x55, 24);
    if (!strcmp(argv[1], "mismatch")) data[0x58ab0e4] = 0;
    Module m = {.base=data, .file_size=len, .text_end=len};
    unsetenv("FC26_PATCHES");
    runtime_game_patches(&m);
    if (!strcmp(argv[1], "off")) assert(data[0x58ab0e4] == 0x55);
    else assert(data[0x58ab0e4] == 0 && data[0x58ab0e5] == 0x79);
    return 0;
}
