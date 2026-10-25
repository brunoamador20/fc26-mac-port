/* Optional read-only time-source diagnostics; no guest clock is adjusted. */
#define FC26_TIME_PROBE_IMPLEMENTATION
#include "time_probe.h"
#include "runtime.h"
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int fc26_time_probe_on;
static _Atomic uint64_t calls[FC_CLOCK_COUNT],last[FC_CLOCK_COUNT];
static uint64_t previous[FC_CLOCK_COUNT],previous_n[FC_CLOCK_COUNT],previous_wall;
static const struct { const char *name;uint64_t hz; } sources[FC_CLOCK_COUNT]={
 {"hardware-main",19200000},{"hardware-nro",19200000},{"GetSystemTick",19200000},
 {"GetSystemTickFrequency",0},{"nn-time-realtime",1000000000},{"nn-time-steady",1},
 {"nn-time-posix",1},{"host-vblank",60},{"vi-vsync-register",0},{"vi-queued-frame",0},
 {"vi-history-count",0},{"nvn-acquire",0},{"nvn-present-interval",0},{"ipc-system-seconds",1},{"ipc-steady-seconds",1},
 {"nvn-host-ns",1000000000},{"nvn-counter-ns",1000000000}
};
__attribute__((constructor)) static void time_probe_init(void) { fc26_time_probe_on=getenv("FC26_TIME_PROFILE")!=NULL; }
void fc26_time_probe_note(unsigned source,uint64_t value) {
 if(!fc26_time_probe_on || source>=FC_CLOCK_COUNT)return;
 atomic_store_explicit(&last[source],value,memory_order_relaxed);
 atomic_fetch_add_explicit(&calls[source],1,memory_order_relaxed);
}
void dm_time_profile_frame(uint64_t frame) {
 if(!fc26_time_probe_on)return;
 uint64_t now=runtime_now_ns();
 fprintf(stderr,"[fc26-time] frame=%llu wall_ms=%.3f",(unsigned long long)frame,previous_wall?(now-previous_wall)/1e6:0.0);
 for(unsigned i=0;i<FC_CLOCK_COUNT;i++) {
  uint64_t n=atomic_load_explicit(&calls[i],memory_order_relaxed),v=atomic_load_explicit(&last[i],memory_order_relaxed);
  int64_t delta=(int64_t)(v-previous[i]);
  fprintf(stderr," %s:n=%llu,v=%llu,d=%lld,ms=%.6f",sources[i].name,(unsigned long long)(n-previous_n[i]),(unsigned long long)v,(long long)(previous_n[i]?delta:0),
   sources[i].hz && previous_n[i]?delta*1000.0/sources[i].hz:0.0);
  previous_n[i]=n;previous[i]=v;
 }
 fputc('\n',stderr);previous_wall=now;
}
static uint64_t profiled_frequency(void) {fc26_clock_note(FC_CLOCK_FREQUENCY,19200000);return 19200000;}
void *runtime_time_probe_override(const char *name) {
 if(!fc26_time_probe_on)return NULL;
 if(!strcmp(name,"_ZN2nn2os22GetSystemTickFrequencyEv"))return profiled_frequency;
 return NULL;
}
