#include "../runtime/app_bootstrap.h"
int main(void) {
    if (fc26_apply_app_bootstrap()) return 7;
    if (fc26_apply_app_bootstrap()) return 9; /* Envelope was consumed: no second rotation. */
    char cwd[4096]; if (!getcwd(cwd, sizeof cwd)) return 8;
    fprintf(stdout, "stdout:%s:%s:%s\n", cwd, getenv("KEEP") ?: "missing", getenv("TOTK_HEADLESS") ?: "absent");
    fprintf(stderr, "stderr:%s\n", getenv("FC26_APP_BOOTSTRAP") ?: "consumed");
    return 0;
}
