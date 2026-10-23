/* Horizon services the TotK host never needed, answered in-process over IPC (ipc.c), and SDK functions answered by name
   (runtime_game_override): offline settings, sockets, network and account answers carried over from the kit's
   earlier fork, where each one was met. FC 26 imports the same libraries (BRIEFING: os, fs, hid, friends, account, socket, oe,
   nifm, time, ...); whether it calls each of these is to be seen at boot. Command numbers and layouts follow the public
   switchbrew descriptions. Unknown services and commands still stop the runtime with their name and id (ipc.c). */
#include "runtime.h"
#include "ipc.h"
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <stdlib.h>
#include <unistd.h>
#include "game_version.h"

/* ---------- set: nn::settings ISettingsServer ---------- */
/* nn::settings::Language order -> language code (switchbrew "Settings services", LanguageCode). */
static const char *const language_codes[] = {
    "ja", "en-US", "fr", "de", "it", "es", "zh-CN", "ko", "nl", "pt", "ru", "zh-TW", "en-GB", "fr-CA", "es-419",
    "zh-Hans", "zh-Hant", "pt-BR",
};
enum { LANGUAGES = sizeof language_codes / sizeof *language_codes, REGION_USA = 1 };

static uint64_t code_of(unsigned language) {
    uint64_t v = 0;
    memcpy(&v, language_codes[language], strlen(language_codes[language]));
    return v;
}
/* Writes up to `room` codes into a guest out buffer; returns how many. */
static int32_t write_codes(uint64_t addr, uint64_t size) {
    uint64_t *out = ipc_guest(addr, size);
    int32_t n = 0;
    for (; n < LANGUAGES && (uint64_t)(n + 1) * 8 <= size; n++) out[n] = code_of((unsigned)n);
    return n;
}
static void settings_handler(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {
    switch (rq->cmd) {
    case 0: { uint64_t v = runtime_desired_language(); IPC_OUT(rs, v); return; }   /* GetLanguageCode */
    case 1: {                                                                    /* GetAvailableLanguageCodes (C buffer) */
        if (!rq->nc) runtime_fail("set GetAvailableLanguageCodes: no output buffer");
        int32_t n = write_codes(rq->c[0].addr, rq->c[0].size);
        rs->xout[rs->nxout++] = (IpcBuffer){rq->c[0].addr, (uint64_t)n * 8, 0};
        IPC_OUT(rs, n); return;
    }
    case 2: {                                                                    /* MakeLanguageCode(Language) */
        uint32_t language = IPC_ARG(rq, uint32_t, 0);
        if (language >= LANGUAGES) { fprintf(stderr, "[totk-set] MakeLanguageCode(%u)\n", language); runtime_fail("set MakeLanguageCode: unknown language"); }
        uint64_t v = code_of(language); IPC_OUT(rs, v); return;
    }
    case 3: case 6: { int32_t n = LANGUAGES; IPC_OUT(rs, n); return; }          /* GetAvailableLanguageCodeCount(2) */
    case 4: { int32_t v = REGION_USA; IPC_OUT(rs, v); return; }                   /* GetRegionCode */
    case 5: {                                                                    /* GetAvailableLanguageCodes2 (B buffer) */
        if (!rq->nb) runtime_fail("set GetAvailableLanguageCodes2: no output buffer");
        int32_t n = write_codes(rq->b[0].addr, rq->b[0].size); IPC_OUT(rs, n); return;
    }
    case 8: { uint8_t v = 0; IPC_OUT(rs, v); return; }                            /* GetQuestFlag: not a kiosk unit */
    default: ipc_unimplemented(s, rq);
    }
}

/* ---------- bsd:u: nn::socket, offline ---------- */
/* The game is played offline, as a Switch without a connection: the client registers and its monitor starts, but every
   socket it asks for fails with ENETDOWN. Commands return {s32 ret, u32 errno} (switchbrew "Sockets services"). */
enum { BSD_ENETDOWN = 50 };
static void bsd_result(IpcResponse *rs, int32_t ret, uint32_t err) { IPC_OUT(rs, ret); IPC_OUT(rs, err); }
static void bsd_handler(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {
    switch (rq->cmd) {
    case 0: { uint64_t pid = 0; IPC_OUT(rs, pid); return; }                         /* RegisterClient(config, tmem) */
    case 1: return;                                                               /* StartMonitoring(pid) */
    case 2: case 3:                                                               /* Socket / SocketExempt */
        fprintf(stderr, "[totk-net] socket(%u, %u, %u) refused: offline\n", IPC_ARG(rq, uint32_t, 0), IPC_ARG(rq, uint32_t, 4), IPC_ARG(rq, uint32_t, 8));
        bsd_result(rs, -1, BSD_ENETDOWN); return;
    case 5: case 6:                                                               /* Select / Poll (0 ready, no error) */
        bsd_result(rs, 0, 0); return;
    case 7:                                                                       /* Sysctl (offline: refused) */
        bsd_result(rs, -1, BSD_ENETDOWN); return;
    case 24:                                                                      /* Close */
        bsd_result(rs, 0, 0); return;
    default: ipc_unimplemented(s, rq);
    }
}

/* ---------- time:u / time:a / ITimeZoneService ---------- */
/* Standard horizon time services backed by the host clock and local time zone. */
static void get_device_location_name(char out[0x24]) {
    memset(out, 0, 0x24);
    #if defined(__APPLE__) || defined(__linux__)
    char link[512]; ssize_t n = readlink("/etc/localtime", link, sizeof link - 1);
    if (n > 0) {
        link[n] = 0; const char *z = strstr(link, "zoneinfo/");
        snprintf(out, 0x24, "%s", z ? z + 9 : "UTC");
        return;
    }
    #endif
    snprintf(out, 0x24, "UTC");
}

typedef struct { int16_t year; int8_t month, day, hour, minute, second, pad; } IpcCalendarTime;
typedef struct { int32_t day_of_week, day_of_year; char name[8]; uint8_t dst, pad[3]; int32_t utc_offset; } IpcCalendarInfo;

static void timezone_handler(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {
    switch (rq->cmd) {
    case 0: {                                                                    /* GetDeviceLocationName */
        char name[0x24]; get_device_location_name(name);
        ipc_out(rs, name, sizeof name); return;
    }
    case 1: return;                                                              /* SetDeviceLocationName */
    case 2: { uint32_t count = 1; IPC_OUT(rs, count); return; }                  /* GetTotalLocationNameCount */
    case 3: {                                                                    /* LoadLocationNameList */
        char name[0x24]; get_device_location_name(name); uint32_t count = 0;
        if (rq->nb > 0 && rq->b[0].size >= sizeof name) {
            memcpy(ipc_guest(rq->b[0].addr, sizeof name), name, sizeof name);
            count = 1;
        }
        IPC_OUT(rs, count); return;
    }
    case 4: {                                                                    /* LoadTimeZoneRule */
        if (rq->nb > 0) memset(ipc_guest(rq->b[0].addr, rq->b[0].size), 0, (size_t)rq->b[0].size);
        return;
    }
    case 5: {                                                                    /* GetTimeZoneRuleVersion */
        char ver[0x10] = "2024b"; ipc_out(rs, ver, sizeof ver); return;
    }
    case 100: case 101: {                                                        /* ToCalendarTime(WithMyRule) */
        int64_t posix = IPC_ARG(rq, int64_t, 0);
        time_t t = (time_t)posix; struct tm tm;
        if (!localtime_r(&t, &tm)) gmtime_r(&t, &tm);
        IpcCalendarTime cal = {
            (int16_t)(tm.tm_year + 1900), (int8_t)(tm.tm_mon + 1), (int8_t)tm.tm_mday,
            (int8_t)tm.tm_hour, (int8_t)tm.tm_min, (int8_t)tm.tm_sec, 0
        };
        IpcCalendarInfo info;
        memset(&info, 0, sizeof info);
        info.day_of_week = tm.tm_wday; info.day_of_year = tm.tm_yday;
        #if defined(__APPLE__) || defined(__linux__)
        snprintf(info.name, sizeof info.name, "%s", tm.tm_zone ? tm.tm_zone : "UTC");
        info.utc_offset = (int32_t)tm.tm_gmtoff;
        #else
        snprintf(info.name, sizeof info.name, "UTC");
        #endif
        info.dst = tm.tm_isdst > 0;
        IPC_OUT(rs, cal); IPC_OUT(rs, info); return;
    }
    case 201: {                                                                  /* ToPosixTimeWithMyRule */
        IpcCalendarTime cal = IPC_ARG(rq, IpcCalendarTime, 0);
        struct tm tm = {0};
        tm.tm_year = cal.year - 1900; tm.tm_mon = cal.month - 1; tm.tm_mday = cal.day;
        tm.tm_hour = cal.hour; tm.tm_min = cal.minute; tm.tm_sec = cal.second;
        tm.tm_isdst = -1;
        time_t t = mktime(&tm);
        uint32_t count = 1; IPC_OUT(rs, count);
        int64_t posix[2] = {(int64_t)t, 0};
        IPC_OUT(rs, posix); return;
    }
    default: ipc_unimplemented(s, rq);
    }
}

static void clock_handler(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {
    switch (rq->cmd) {
    case 0: { int64_t now = (int64_t)time(NULL); IPC_OUT(rs, now); return; }   /* GetCurrentTime */
    case 1: return;                                                             /* SetCurrentTime */
    case 2: {                                                                   /* GetSystemClockContext */
        struct { int64_t offset; struct { int64_t val; uint8_t src[16]; } pt; } ctx;
        memset(&ctx, 0, sizeof ctx); ctx.pt.val = (int64_t)time(NULL); ctx.pt.src[0] = 1;
        IPC_OUT(rs, ctx); return;
    }
    case 3: return;                                                             /* SetSystemClockContext */
    default: ipc_unimplemented(s, rq);
    }
}

static void steady_clock_handler(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {
    switch (rq->cmd) {
    case 0: {                                                                   /* GetCurrentTimePoint */
        struct { int64_t val; uint8_t src[16]; } pt;
        memset(&pt, 0, sizeof pt); pt.val = (int64_t)time(NULL); pt.src[0] = 1;
        IPC_OUT(rs, pt); return;
    }
    default: ipc_unimplemented(s, rq);
    }
}

static void time_service_handler(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {
    switch (rq->cmd) {
    case 0: case 1: case 4: case 5:                                             /* GetStandardUserSystemClock / Network / Local / Ephemeral */
        rs->move[rs->nmove++] = runtime_ipc_new_session("ISystemClock", clock_handler, NULL, NULL); return;
    case 2:                                                                     /* GetStandardSteadyClock */
        rs->move[rs->nmove++] = runtime_ipc_new_session("ISteadyClock", steady_clock_handler, NULL, NULL); return;
    case 3:                                                                     /* GetTimeZoneService */
        rs->move[rs->nmove++] = runtime_ipc_new_session("ITimeZoneService", timezone_handler, NULL, NULL); return;
    default: ipc_unimplemented(s, rq);
    }
}

/* ---------- SDK functions answered by name (runtime_game_override) ----------
   Network-facing libraries answer as a Switch without a connection. The failure results are generic ones of each
   library's module (nifm 110, ssl 123, account 124), not a specific console error: the game only needs "unavailable". */
#define RESULT(module, description) ((uint32_t)(module) | ((uint32_t)(description) << 9))
#define NIFM_UNAVAILABLE RESULT(110, 300)
#define SSL_UNAVAILABLE RESULT(123, 300)
#define NSA_UNAVAILABLE RESULT(124, 280)
static void nop(void) {}
static uint32_t ok(void) { return 0; }
static uint8_t network_available(void) { return 0; }
static uint32_t nifm_unavailable(void) { return NIFM_UNAVAILABLE; }
static uint32_t ssl_unavailable(void) { return SSL_UNAVAILABLE; }
static uint32_t nsa_unavailable(void) { return NSA_UNAVAILABLE; }
static void nifm_request(void) { static int once; if (!once++) fprintf(stderr, "[totk-net] network request: offline\n"); }
static int64_t network_clock_now(void) { return (int64_t)time(NULL); }   /* time_point: seconds since the epoch */
static void environment_identifier(char *out) { if (!out) runtime_fail("nsd environment output"); memset(out, 0, 8); memcpy(out, "lp1", 3); }
static void execute_program(int index, const void *param, uint64_t size) {
    (void)param; fprintf(stderr, "[totk] nn::oe::ExecuteProgram(%d, %llu bytes): program title %016llX\n", index, (unsigned long long)size,
                         (unsigned long long)(GAME_TITLE_ID + (uint64_t)index));
    runtime_missing("sdk function: nn::oe::ExecuteProgram program index %d", index);
    runtime_fail("the game asked to start another program of its title (nn::oe::ExecuteProgram), which is not supported yet");
}
/* Open users kept across a program jump (PushOpenUsers before ExecuteProgram, PopOpenUsers in the next program). A
   fresh start has none; the game then opens its user the usual way (runtime/account.c). */
static void push_open_users(void) {}
static uint32_t pop_open_users(int32_t *count, void *handles, int32_t max) {
    (void)handles; (void)max; if (!count) runtime_fail("PopOpenUsers count pointer"); *count = 0; return 0;
}
void *runtime_game_override(const char *name) {
    static const struct { const char *name; void *fn; } entries[] = {
        {"_ZN2nn2oe13MuteRecordingEv", nop}, {"_ZN2nn2oe15UnmuteRecordingEv", nop},
        {"_ZN2nn2oe15EnableRecordingEv", nop}, {"_ZN2nn2oe16DisableRecordingEv", nop},
        {"_ZN2nn2oe14ExecuteProgramEiPKvm", execute_program},
        {"_ZN2nn4nifm10InitializeEv", ok}, {"_ZN2nn4nifm18IsNetworkAvailableEv", network_available},
        {"_ZN2nn4nifm27SubmitNetworkRequestAndWaitEv", nifm_request}, {"_ZN2nn4nifm20CancelNetworkRequestEv", nop},
        {"_ZN2nn4nifm31HandleNetworkRequestErrorResultEv", nifm_unavailable},
        {"_ZN2nn4nifm22GetCurrentProxySettingEPNS0_12ProxySettingE", nifm_unavailable},
        {"_ZN2nn4nifm26GetCurrentPrimaryIpAddressEPNS_6socket6InAddrE", nifm_unavailable},
        {"_ZN2nn3ssl10InitializeEv", ok}, {"_ZN2nn3ssl8FinalizeEv", ok},
        {"_ZN2nn3ssl14BuiltInManager22GetBuiltInCertificatesEPPNS0_26BuiltInCertificateInfoBaseEPhjPNS0_15CaCertificateIdEj", ssl_unavailable},
        {"_ZN2nn3ssl14BuiltInManager28GetBuiltInCertificateBufSizeEPjPNS0_15CaCertificateIdEj", ssl_unavailable},
        {"_ZN2nn7account36EnsureNetworkServiceAccountAvailableERKNS0_10UserHandleE", nsa_unavailable},
        {"_ZN2nn7account26GetNetworkServiceAccountIdEPNS0_23NetworkServiceAccountIdERKNS0_10UserHandleE", nsa_unavailable},
        {"_ZN2nn7account37LoadNetworkServiceAccountIdTokenCacheEPmPcmRKNS0_10UserHandleE", nsa_unavailable},
        {"_ZN2nn7account44EnsureNetworkServiceAccountIdTokenCacheAsyncEPNS0_12AsyncContextERKNS0_10UserHandleE", nsa_unavailable},
        {"_ZN2nn7friends12UserPresence10InitializeERKNS_7account3UidE", ok},
        {"_ZN2nn4time26StandardNetworkSystemClock3nowEv", network_clock_now},
        {"_ZN2nn3err21ReportMultimediaErrorENS_6ResultERKN5movie25MultimediaTelemetryReportE", nop},
        {"_ZN2nn3nsd24GetEnvironmentIdentifierEPNS0_21EnvironmentIdentifierE", environment_identifier},
        {"_ZN2nn5prepo10InitializeEv", nop},
        {"_ZN2nn3hid18StartSixAxisSensorERKNS0_19SixAxisSensorHandleE", nop},
        {"_ZN2nn7account13PushOpenUsersEv", push_open_users},
        {"_ZN2nn7account12PopOpenUsersEPiPNS0_10UserHandleEi", pop_open_users},
    };
    for (size_t i = 0; i < sizeof entries / sizeof *entries; i++) if (!strcmp(name, entries[i].name)) return entries[i].fn;
    return NULL;
}

__attribute__((constructor)) static void register_system_services(void) {
    /* Graphics-layer settings. Each one is the earlier fork's choice, kept because it is not about one game:
       TODO(mac): confirm each for FC 26 at the first frame (story 4). The earlier fork also set DM_POOL_BUFFER_MAX_MIB=2048
       for its game's 1348 MiB NVN memory pool; FC 26's largest pool is not known, so the layer's default (1024 MiB) stands and
       a larger pool stops the game with its size and this variable's name (nvn_mtl.m pool_range_check).
       Present pacing as on the Switch: a 60 Hz base, the game's present interval on top (1 = 60 fps, 2 = 30 fps). The
       TotK host follows the display (120 Hz on ProMotion) and runs uncapped, which relies on TotK's real-time frame step
       patch; without it a game that advances per frame would run twice as fast. */
    setenv("DM_PRESENT_HZ", "60", 0);
    setenv("TOTK_UNCAPPED", "0", 0);
    /* A depth pre-pass followed by a colour pass with a LEQUAL test needs positions that match bit for bit between the
       two (nvn_mtl.m totk_precise_opts, preserveInvariance). Whether FC 26 draws such a pair is not known yet. */
    setenv("DM_PRESERVE_INVARIANCE", "1", 0);
    /* Shader binaries newer than the graphics layer's measured driver table (1.14) were met in the earlier fork (SDK 13.3.2:
       1.15, 1.16); FC 26's SDK 19.3.4 is newer still. TODO(mac): read the GPU code version of FC 26's shaders (VSO header
       bytes 6/7, in the shaderBlockDepot of the .cas files). The layer reads only three control-section fields (code
       length, stage, compute group size) and stops on implausible values, so a newer layout would show at once. */
    setenv("DM_NVN_GPU_CODE_MAX_MINOR", "31", 0);
    runtime_ipc_register("set", settings_handler, NULL, NULL);
    runtime_ipc_register("bsd:u", bsd_handler, NULL, NULL);
    runtime_ipc_register("time:u", time_service_handler, NULL, NULL);
    runtime_ipc_register("time:a", time_service_handler, NULL, NULL);
    runtime_ipc_register("time:s", time_service_handler, NULL, NULL);
    runtime_ipc_register("time:m", time_service_handler, NULL, NULL);
}
