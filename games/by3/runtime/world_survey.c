#include "world_survey.h"

/* The TotK world survey reads TotK's actor and scene structures; Bayonetta 3 has none of them. Commands are refused. */
_Atomic int runtime_survey_pending;
void runtime_survey_init(Module *main_module) { (void)main_module; }
int runtime_survey_command(const char *line) { (void)line; return 0; }
void runtime_survey_tick(uint64_t frame) { (void)frame; }
void runtime_survey_cancel_user(void) {}
