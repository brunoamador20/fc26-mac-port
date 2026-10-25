#pragma once
#include <stdint.h>
enum {
 FC_CLOCK_MAIN_TICK, FC_CLOCK_RO_TICK, FC_CLOCK_SYSTEM_TICK, FC_CLOCK_FREQUENCY,
 FC_CLOCK_REALTIME_NS, FC_CLOCK_STEADY_SEC, FC_CLOCK_POSIX_SEC,
 FC_CLOCK_VBLANK, FC_CLOCK_VSYNC_REGISTER, FC_CLOCK_VI_FRAME, FC_CLOCK_VI_HISTORY,
 FC_CLOCK_NVN_ACQUIRE, FC_CLOCK_NVN_PRESENT, FC_CLOCK_IPC_SYSTEM_SEC, FC_CLOCK_IPC_STEADY_SEC, FC_CLOCK_NVN_HOST_NS, FC_CLOCK_NVN_COUNTER_NS, FC_CLOCK_COUNT
};
#ifdef FC26_TIME_PROBE_IMPLEMENTATION
extern int fc26_time_probe_on;
void fc26_time_probe_note(unsigned source,uint64_t value);
#else
#ifdef __APPLE__
#define FC26_PROBE_OPTIONAL __attribute__((weak_import))
#else
#define FC26_PROBE_OPTIONAL __attribute__((weak))
#endif
extern int fc26_time_probe_on FC26_PROBE_OPTIONAL;
void fc26_time_probe_note(unsigned source,uint64_t value) FC26_PROBE_OPTIONAL;
#endif
static inline void fc26_clock_note(unsigned source,uint64_t value) {
#ifdef FC26_TIME_PROBE_IMPLEMENTATION
 if(fc26_time_probe_on)fc26_time_probe_note(source,value);
#else
 if (&fc26_time_probe_on && fc26_time_probe_on && fc26_time_probe_note) fc26_time_probe_note(source,value);
#endif
}
