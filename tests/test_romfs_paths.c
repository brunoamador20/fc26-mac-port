/* Test the production path parser with synthetic names; no game files/keys. */
#include "../games/totk/runtime/romfs_path.h"
#include <stdio.h>

typedef struct { const char *mount, *path, *expected; } Case;
int main(void) {
    const Case cases[] = {
        {"content", "content:/Sound/Resource/Stream/opening.bwav", "Sound/Resource/Stream/opening.bwav"},
        {"content", "content://Sound/Resource/Stream/opening.bwav", "Sound/Resource/Stream/opening.bwav"},
        {"content", "content:///Sound/Resource/Stream/opening.bwav", "Sound/Resource/Stream/opening.bwav"},
        {"content", "content:////Sound/Resource/Stream/opening.bwav", "Sound/Resource/Stream/opening.bwav"},
        {"rom", "rom://UI/layout.bin", "UI/layout.bin"},
        {"rom", "rom:/dir/a..b", "dir/a..b"},
        {"rom", "rom:/dir/.hidden", "dir/.hidden"},
        {"rom", "rom:/dir/文件.bin", "dir/文件.bin"},
        {NULL, "rom:/file", NULL},
        {"", "rom:/file", NULL},
        {"rom", NULL, NULL},
        {"rom", "", NULL},
        {"rom", "ro", NULL},
        {"rom", "rom", NULL},
        {"rom", "rom:", NULL},
        {"rom", "rom:file", NULL},
        {"rom", "other:/file", NULL},
        {"rom", "rom2:/file", NULL},
        {"rom", "ROM:/file", NULL},
        {"rom", "rom:/", NULL},
        {"rom", "rom:////", NULL},
        {"rom", "rom://../file", NULL},
        {"rom", "rom:///./file", NULL},
        {"rom", "rom:/dir/../file", NULL},
        {"rom", "rom:/dir/./file", NULL},
        {"rom", "rom:/dir//file", NULL},
        {"rom", "rom://dir\\file", NULL},
    };
    for (size_t i = 0; i < sizeof cases / sizeof cases[0]; ++i) {
        const char *result = romfs_path_relative(cases[i].mount, cases[i].path);
        if ((!result != !cases[i].expected) ||
            (result && strcmp(result, cases[i].expected))) {
            fprintf(stderr, "case %zu failed: %s -> %s (expected %s)\n", i,
                    cases[i].path ? cases[i].path : "(null)",
                    result ? result : "(null)",
                    cases[i].expected ? cases[i].expected : "(null)");
            return 1;
        }
    }
    printf("PASS: %zu RomFS path cases\n", sizeof cases / sizeof cases[0]);
    return 0;
}
