/* Breath of the Wild game-code patches (botw.md). None yet: the game runs as shipped. The functions the shared runtime
   calls (frame step, output size, key 3 / key 4) answer "not available" until BotW's own sites are found. */
#include <stdio.h>
#include "game_patches.h"
#include "game_version.h"

void runtime_frame_step_pin(double ms) { (void)ms; }
void runtime_frame_step_update(uint64_t now_ns) { (void)now_ns; }
void runtime_game_patches(Module *m) { (void)m; fprintf(stderr, "[botw] %s: no game-code patches\n", TOTK_GAME_VERSION); }
int runtime_output_res(unsigned *w, unsigned *h) { (void)w; (void)h; return 0; }
uint64_t runtime_output_res_extra_bytes(void) { return 0; }
int runtime_output_res_toggle(void) { return 0; }
int runtime_output_mode_cycle(void) { fprintf(stderr, "[botw] key 3: no 2K modes yet\n"); return 0; }
float runtime_aspect_now(void) { return 0; }
int runtime_aspect_toggle(void) { return 0; }
