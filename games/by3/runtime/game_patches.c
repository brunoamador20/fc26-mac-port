#include "game_patches.h"
#include <stdint.h>

/* Bayonetta 3: no game-code patches yet. The TotK ones (60 FPS controller, real-time frame step, output resolution,
   ultrawide) target TotK's code and are not carried over. The host hooks they provide keep their names and answer
   "off", so the shared graphics layer and the input keys work unchanged. The community 1.2.0 patches (60 fps, 900p)
   are for a later stage. */
void runtime_game_patches(Module *main_module) { (void)main_module; }

void runtime_frame_step_pin(double ms) { (void)ms; }
void runtime_frame_step_update(uint64_t now_ns) { (void)now_ns; }
int runtime_output_res(unsigned *w, unsigned *h) { (void)w; (void)h; return 0; }
uint64_t runtime_output_res_extra_bytes(void) { return 0; }
uint64_t runtime_output_size_current(void) { return (uint64_t)1080 << 32 | 1920; }
int runtime_output_res_toggle(void) { return 0; }
int runtime_output_mode_cycle(void) { return 0; }
int runtime_aspect_toggle(void) { return 0; }
float runtime_aspect_now(void) { return 0; }
