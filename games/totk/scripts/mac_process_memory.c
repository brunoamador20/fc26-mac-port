/* Read-only Mac process memory counters. The start-time argument guards PID
   reuse; use game-slot/holder's game_start for an already-owned test process.
   Build: xcrun clang -O2 scripts/mac_process_memory.c -o /tmp/totk-memory
   Run:   /tmp/totk-memory <pid> <start epoch seconds>
   Values retain the SDK's names/units; footprint is not the same as RSS. */
#include <libproc.h>
#include <sys/proc.h>
#include <sys/resource.h>
#include <inttypes.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static uint64_t process_start(int pid) {
    struct proc_bsdinfo info;
    if (proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &info, sizeof info) != sizeof info || info.pbi_status == SZOMB)
        return 0;
    return info.pbi_start_tvsec;
}

int main(int argc, char **argv) {
    if (argc != 3) { fprintf(stderr, "usage: %s <pid> <start epoch seconds>\n", argv[0]); return 2; }
    char *end;
    long value = strtol(argv[1], &end, 10);
    if (*end || value <= 0 || value > INT_MAX) return 2;
    int pid = (int)value;
    uint64_t start = strtoull(argv[2], &end, 10);
    if (*end || !start || process_start(pid) != start) { fprintf(stderr, "process identity changed\n"); return 3; }
    struct rusage_info_v4 info = {0};
    if (proc_pid_rusage(pid, RUSAGE_INFO_V4, (rusage_info_t *)&info) != 0) { perror("proc_pid_rusage"); return 1; }
    if (process_start(pid) != start) { fprintf(stderr, "process identity changed during sample\n"); return 3; }
    printf("{\"time\":%lld,\"pid\":%d,\"start\":%" PRIu64
           ",\"resident_size\":%" PRIu64 ",\"phys_footprint\":%" PRIu64
           ",\"lifetime_max_phys_footprint\":%" PRIu64 ",\"wired_size\":%" PRIu64
           ",\"pageins\":%" PRIu64 ",\"diskio_bytesread\":%" PRIu64 ",\"diskio_byteswritten\":%" PRIu64 "}\n",
           (long long)time(NULL), pid, start, info.ri_resident_size, info.ri_phys_footprint,
           info.ri_lifetime_max_phys_footprint, info.ri_wired_size, info.ri_pageins,
           info.ri_diskio_bytesread, info.ri_diskio_byteswritten);
    return 0;
}
