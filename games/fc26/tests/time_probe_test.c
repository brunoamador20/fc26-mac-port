/* Exercise the real diagnostic, including its default-off contract. */
#include "../runtime/time_probe.c"
#include <assert.h>
static uint64_t fake_now=1000000000;
uint64_t runtime_now_ns(void) {return fake_now;}
int main(int argc,char **argv) {
 (void)argv;
 if(argc==1) {
  assert(!fc26_time_probe_on);
  assert(!runtime_time_probe_override("_ZN2nn2os22GetSystemTickFrequencyEv"));
  fc26_clock_note(FC_CLOCK_MAIN_TICK,640000);
  assert(!atomic_load(&calls[FC_CLOCK_MAIN_TICK]));
  dm_time_profile_frame(1);return 0;
 }
 assert(fc26_time_probe_on);
 uint64_t (*frequency)(void)=runtime_time_probe_override("_ZN2nn2os22GetSystemTickFrequencyEv");
 assert(frequency && frequency()==19200000);
 /* GetSystemTick must still execute its original SDK gate. */
 assert(!runtime_time_probe_override("_ZN2nn2os13GetSystemTickEv"));
 fc26_clock_note(FC_CLOCK_MAIN_TICK,640000);
 fc26_clock_note(FC_CLOCK_VBLANK,2);dm_time_profile_frame(1);
 fake_now+=33333333;
 fc26_clock_note(FC_CLOCK_MAIN_TICK,1280000);
 fc26_clock_note(FC_CLOCK_VBLANK,4);dm_time_profile_frame(2);
 fc26_time_probe_note(FC_CLOCK_COUNT,123);return 0;
}
