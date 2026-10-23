/* Horizon services FC 26's sdk names that the host did not answer, served over IPC (ipc.c) as a Switch without a
   connection answers them (story 4; docs/SERVICOS_NUVEM.md has the table, the sources and what the Mac checks):
     aoc:u                          no add-on content (nn::aoc::Count/ListAddOnContent are also answered by name, services.c)
     pctl, pctl:a, pctl:s, pctl:r   no parental restriction
     ldn:u, ldn:s, ldn:m            local wireless with nobody around: Scan finds no network, creating or joining one fails
     nim:eca, nim:ecas              the shop service behind nn::ec::ShopServiceAccessor: every request fails as offline
   The sdk's own client code (nn::aoc, nn::pctl, nn::ldn, nn::ec) runs unchanged and reaches these. Command numbers, states
   and results follow switchbrew (pages "NS services" aoc:u, "Parental Control services", "LDN services", "NIM services",
   "Error codes"; read 2026-10-23); where switchbrew gives no layout, the answer is one that needs none (a result only).
   Commands without an offline answer still stop with their name and number (ipc.c). */
#include "runtime.h"
#include "ipc.h"
#include "game_version.h"
#include <pthread.h>
#include <stdio.h>
#include <string.h>

#define RESULT(module, description) ((uint32_t)(module) | ((uint32_t)(description) << 9))
#define LDN_WIRELESS_OFF RESULT(203, 22)        /* 2203-0022: the choice for "no wireless" (docs/SERVICOS_NUVEM.md) */
#define LDN_INVALID_PROTOCOL RESULT(203, 29)    /* 2203-0029 Invalid Protocol */
#define LDN_NOT_INITIALIZED RESULT(203, 37)     /* 2203-0037 State is not Initialized */
#define LDN_INVALID_STATE RESULT(203, 39)       /* 2203-0039 Invalid State or state field */
#define LDN_INVALID_ARGUMENT RESULT(203, 96)    /* 2203-0096 Invalid input or state */
#define EC_INTERNET_NOT_ACCEPTED RESULT(164, 56)/* 2164-0056 ResultInternetRequestNotAccepted (module 164 = Ec) */

/* One event for the "something changed" notifications that never come offline (DLC list, purchases, pairing...): each
   request copies a new readable handle of it, as audio_mixer.c does for its device events. */
static uint32_t quiet_event_w;
static void quiet_event_make(void) { quiet_event_w = runtime_event_new(); }
static uint32_t quiet_event(void) {
    static pthread_once_t once = PTHREAD_ONCE_INIT;
    pthread_once(&once, quiet_event_make);
    return runtime_event_readable(quiet_event_w);
}
static void new_object(IpcResponse *rs, const char *name, IpcHandler handler, void *state, void (*close)(void *)) {
    rs->move[rs->nmove++] = runtime_ipc_new_session(name, handler, state, close);
}

/* ---------- aoc:u: nn::aocsrv::detail::IAddOnContentManager, no DLC (switchbrew "NS services") ----------
   FC 26 1.0.0 is played without add-on content (BRIEFING: no update, no DLC). Inputs (pid placeholder, offset/count,
   delivery targets) are not needed: every answer is "none". */
static void purchase_event_handler(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {   /* nn::ec::IPurchaseEventManager */
    switch (rq->cmd) {
    case 0: case 1: return;                                          /* SetDefaultDeliveryTarget / SetDeliveryTarget */
    case 2: rs->copy[rs->ncopy++] = quiet_event(); return;           /* GetPurchasedEventReadableHandle: nothing is bought */
    default: ipc_unimplemented(s, rq);                               /* 3/4 PopPurchasedProductInfo: only after that event */
    }
}
static void aoc_handler(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {
    switch (rq->cmd) {
    case 2: case 3: { int32_t n = 0; IPC_OUT(rs, n); return; }       /* CountAddOnContent / ListAddOnContent: 0, buffer untouched */
    case 5: { uint64_t base = GAME_TITLE_ID + 0x1000; IPC_OUT(rs, base); return; }   /* GetAddOnContentBaseId (application id + 0x1000) */
    case 8: case 10: rs->copy[rs->ncopy++] = quiet_event(); return;  /* GetAddOnContentListChangedEvent(WithProcessId): never changes */
    case 50: return;                                                 /* CheckAddOnContentMountStatus: nothing mounted, nothing lost */
    case 100: case 101:                                              /* Create(Permanent)EcPurchasedEventManager */
        new_object(rs, "IPurchaseEventManager", purchase_event_handler, NULL, NULL); return;
    default: ipc_unimplemented(s, rq);                               /* 7 PrepareAddOnContent: there is no content to prepare */
    }
}

/* ---------- pctl, pctl:a, pctl:s, pctl:r: nn::pctl, no restriction (switchbrew "Parental Control services") ----------
   The console has no parental controls set: every permission is granted, free communication is available, no play
   timer runs and no pairing exists. Confirm/Check commands answer with their result only. */
static void pctl_handler(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {   /* IParentalControlService */
    uint8_t no = 0, yes = 1;
    switch (rq->cmd) {
    case 1: return;                                                  /* Initialize */
    case 1001: case 1002: case 1003: case 1004: case 1005:           /* CheckFreeCommunicationPermission, Confirm{LaunchApplication,
                                                                        ResumeApplication,SnsPost,SystemSettings}Permission */
    case 1013: case 1016: return;                                    /* ConfirmStereoVisionPermission, ConfirmShowNewsPermission */
    case 1017: case 1018: return;                                    /* EndFreeCommunication, IsFreeCommunicationAvailable (result only) */
    case 1006: IPC_OUT(rs, no); return;                              /* IsRestrictionTemporaryUnlocked */
    case 1031: IPC_OUT(rs, no); return;                              /* IsRestrictionEnabled */
    case 1065: IPC_OUT(rs, yes); return;                             /* IsStereoVisionPermitted */
    case 1403: IPC_OUT(rs, no); return;                              /* IsPairingActive */
    case 1451: case 1452: return;                                    /* StartPlayTimer / StopPlayTimer */
    case 1453: case 1455: IPC_OUT(rs, no); return;                   /* IsPlayTimerEnabled / IsRestrictedByPlayTimer */
    case 1432: case 1457: case 1473:                                 /* GetSynchronizationEvent, GetPlayTimerEventToRequestSuspension,
                                                                        GetUnlinkedEvent: never signalled */
        rs->copy[rs->ncopy++] = quiet_event(); return;
    default: ipc_unimplemented(s, rq);
    }
}
static void pctl_factory(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {   /* IParentalControlServiceFactory */
    switch (rq->cmd) {
    case 0: case 1: new_object(rs, "IParentalControlService", pctl_handler, NULL, NULL); return;   /* CreateService(WithoutInitialize) */
    default: ipc_unimplemented(s, rq);
    }
}

/* ---------- ldn:u, ldn:s, ldn:m: nn::ldn, local wireless with nobody around (switchbrew "LDN services") ----------
   The state machine is switchbrew's (State: 0 None, 1 Initialized, 2 AccessPoint, 3 AccessPointCreated, 4 Station,
   5 StationConnected, 6 Error) with its preconditions; a command in the wrong state gets 2203-0037 (not initialized) or
   2203-0039. Offline: opening an access point or a station works, Scan finds no network (count 0), and creating a network
   (CreateNetwork*) or joining one (Connect*) fails with LDN_WIRELESS_OFF, so states 3 and 5 are never reached. One
   wireless device: the state is shared by every session, as the monitor service (ldn:m) reports it, and no session keeps
   state of its own (a clone made by the sdk's session manager shares the original's handler; only the original closes). */
enum { LDN_NONE, LDN_INITIALIZED, LDN_ACCESS_POINT, LDN_ACCESS_POINT_CREATED, LDN_STATION, LDN_STATION_CONNECTED };
enum { NETWORK_INFO_SIZE = 0x480, ADVERTISE_MAX = 0x180 };
static pthread_mutex_t ldn_lock = PTHREAD_MUTEX_INITIALIZER;
static unsigned ldn_state;
static uint32_t ldn_event_w;
static void ldn_event_make(void) { ldn_event_w = runtime_event_new(); }
static uint32_t ldn_event(void) {
    static pthread_once_t once = PTHREAD_ONCE_INIT;
    pthread_once(&once, ldn_event_make);
    return ldn_event_w;
}
static uint32_t ldn_need(unsigned lo, unsigned hi) {
    return ldn_state >= lo && ldn_state <= hi ? 0 : ldn_state == LDN_NONE ? LDN_NOT_INITIALIZED : LDN_INVALID_STATE;
}
static void ldn_set(unsigned state) {   /* ldn_lock held; GetStateChangeEvent is signalled on every change */
    if (ldn_state == state) return;
    ldn_state = state;
    runtime_event_signal(ldn_event());
}
/* Commands that read the current network (State 3 or 5): there never is one offline. */
static uint32_t ldn_no_network(void) { return ldn_state == LDN_NONE ? LDN_NOT_INITIALIZED : LDN_INVALID_STATE; }
static uint32_t ldn_initialize(void) {
    if (ldn_state == LDN_NONE) ldn_set(LDN_INITIALIZED);   /* already initialized: kept as it is */
    return 0;
}
static uint32_t ldn_scan(const IpcRequest *rq, IpcResponse *rs) {
    /* Takes s16 channel + ScanFilter (0x60) and a type-0x22 output array of NetworkInfo (0x480 each, at least one);
       returns the s16 count. State 3-5. */
    uint32_t r = ldn_need(LDN_ACCESS_POINT_CREATED, LDN_STATION_CONNECTED);
    if (r) return r;
    int pointer = !(rq->nb && rq->b[0].size);
    const IpcBuffer *out = pointer ? (rq->nc ? &rq->c[0] : NULL) : &rq->b[0];
    if (!out || out->size < NETWORK_INFO_SIZE) return LDN_INVALID_ARGUMENT;
    if (pointer) rs->xout[rs->nxout++] = (IpcBuffer){out->addr, 0, 0};
    int16_t count = 0; IPC_OUT(rs, count);
    static int logged;
    if (!logged++) fprintf(stderr, "[totk-net] ldn Scan: no network (offline)\n");
    return 0;
}
static uint32_t ldn_command(IpcSession *s, int system, const IpcRequest *rq, IpcResponse *rs) {
    unsigned cmd = rq->cmd;
    /* 402-404 differ between the user and the system interface (switchbrew tables). */
    if (system && (cmd == 402 || cmd == 403 || cmd == 404)) cmd = cmd == 402 ? 1403 : cmd == 403 ? 1402 : 1404;
    else if (!system && (cmd == 402 || cmd == 403)) cmd = cmd == 402 ? 1402 : 1403;
    switch (cmd) {
    case 0: { uint32_t v = ldn_state; IPC_OUT(rs, v); return 0; }               /* GetState */
    case 1: case 2: case 4: case 5: case 101: return ldn_no_network();         /* GetNetworkInfo, GetIpv4Address, GetSecurityParameter,
                                                                                  GetNetworkConfig, GetNetworkInfoAndHistory */
    case 3: { int16_t v = 0; IPC_OUT(rs, v); return 0; }                        /* GetDisconnectReason: None */
    case 100: rs->copy[rs->ncopy++] = runtime_event_readable(ldn_event()); return 0;   /* GetStateChangeEvent */
    case 102: case 103: return ldn_scan(rq, rs);                                /* Scan / ScanPrivate */
    case 104: return ldn_need(LDN_INITIALIZED, LDN_INITIALIZED);                /* SetWirelessControllerPolicy */
    case 105: return 0;                                                         /* SetWirelessAudioPolicy */
    case 106: {                                                                 /* SetProtocol(u32): 1 or 3 on NX */
        uint32_t protocol = IPC_ARG(rq, uint32_t, 0), r = ldn_need(LDN_INITIALIZED, LDN_INITIALIZED);
        if (!protocol) return LDN_INVALID_ARGUMENT;
        if (r) return r;
        return protocol == 1 || protocol == 3 ? 0 : LDN_INVALID_PROTOCOL;
    }
    case 200: {                                                                 /* OpenAccessPoint: 1 -> 2 */
        uint32_t r = ldn_need(LDN_INITIALIZED, LDN_INITIALIZED); if (!r) ldn_set(LDN_ACCESS_POINT); return r;
    }
    case 201: {                                                                 /* CloseAccessPoint: 2-3 -> 1 */
        uint32_t r = ldn_need(LDN_ACCESS_POINT, LDN_ACCESS_POINT_CREATED); if (!r) ldn_set(LDN_INITIALIZED); return r;
    }
    case 202: case 203: {                                                       /* CreateNetwork(Private): needs 2; offline */
        uint32_t r = ldn_need(LDN_ACCESS_POINT, LDN_ACCESS_POINT);
        if (r) return r;
        fprintf(stderr, "[totk-net] ldn %s refused: no wireless (offline), result %#x\n", cmd == 202 ? "CreateNetwork" : "CreateNetworkPrivate", LDN_WIRELESS_OFF);
        return LDN_WIRELESS_OFF;
    }
    case 204: case 205: return ldn_need(LDN_ACCESS_POINT_CREATED, LDN_ACCESS_POINT_CREATED);   /* DestroyNetwork / Reject: never 3 */
    case 206: {                                                                 /* SetAdvertiseData(type-0x21 buffer <= 0x180) */
        uint64_t size = rq->na && rq->a[0].size ? rq->a[0].size : rq->nx ? rq->x[0].size : 0;
        uint32_t r = ldn_need(LDN_ACCESS_POINT, LDN_ACCESS_POINT_CREATED);
        return r ? r : size > ADVERTISE_MAX ? LDN_INVALID_ARGUMENT : 0;
    }
    case 207: case 208: case 209: return ldn_need(LDN_ACCESS_POINT, LDN_ACCESS_POINT_CREATED);   /* accept policy and filter */
    case 300: {                                                                 /* OpenStation: 1 -> 4 */
        uint32_t r = ldn_need(LDN_INITIALIZED, LDN_INITIALIZED); if (!r) ldn_set(LDN_STATION); return r;
    }
    case 301: {                                                                 /* CloseStation: 4-5 -> 1 */
        uint32_t r = ldn_need(LDN_STATION, LDN_STATION_CONNECTED); if (!r) ldn_set(LDN_INITIALIZED); return r;
    }
    case 302: case 303: {                                                       /* Connect(Private): needs 4; offline */
        uint32_t r = ldn_need(LDN_STATION, LDN_STATION);
        if (r) return r;
        fprintf(stderr, "[totk-net] ldn %s refused: no wireless (offline), result %#x\n", cmd == 302 ? "Connect" : "ConnectPrivate", LDN_WIRELESS_OFF);
        return LDN_WIRELESS_OFF;
    }
    case 304: return ldn_need(LDN_STATION_CONNECTED, LDN_STATION_CONNECTED);    /* Disconnect: never 5 */
    case 400: return ldn_initialize();                                         /* Initialize(pid, u64) */
    case 401: {                                                                 /* Finalize: any state but None -> None */
        uint32_t r = ldn_need(LDN_INITIALIZED, LDN_STATION_CONNECTED); if (!r) ldn_set(LDN_NONE); return r;
    }
    case 1402: if (IPC_ARG(rq, int32_t, 0) < 0) return LDN_INVALID_ARGUMENT; return ldn_initialize();   /* InitializeWithVersion(s32, pid, u64) */
    case 1403: return ldn_need(LDN_INITIALIZED, LDN_INITIALIZED);               /* SetOperationMode */
    case 1404: if (IPC_ARG(rq, int32_t, 0) < 0) return LDN_INVALID_ARGUMENT; return ldn_initialize();   /* InitializeWithPriority (ldn:s) */
    default: ipc_unimplemented(s, rq);                                          /* action frames, tx power, ... */
    }
}
static void ldn_handle(IpcSession *s, const IpcRequest *rq, IpcResponse *rs, int system) {
    pthread_mutex_lock(&ldn_lock);
    rs->result = ldn_command(s, system, rq, rs);
    pthread_mutex_unlock(&ldn_lock);
}
static void ldn_user(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) { ldn_handle(s, rq, rs, 0); }     /* IUserLocalCommunicationService */
static void ldn_system(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) { ldn_handle(s, rq, rs, 1); }   /* ISystemLocalCommunicationService */
static void ldn_close(void *unused) {   /* the client went away (with or without Finalize): the service finalizes it */
    (void)unused;
    pthread_mutex_lock(&ldn_lock);
    ldn_set(LDN_NONE);
    pthread_mutex_unlock(&ldn_lock);
}
static void ldn_client_monitor(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {   /* IClientProcessMonitor */
    (void)rs;
    if (rq->cmd != 0) ipc_unimplemented(s, rq);                                 /* RegisterClient(pid, u64) */
}
static void ldn_monitor(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {   /* IMonitorService */
    pthread_mutex_lock(&ldn_lock);
    switch (rq->cmd) {
    case 0: { uint32_t v = ldn_state; IPC_OUT(rs, v); break; }                  /* GetState */
    case 1: case 2: case 4: case 5: rs->result = ldn_no_network(); break;
    case 3: { int16_t v = 0; IPC_OUT(rs, v); break; }                           /* GetDisconnectReason */
    case 100: case 101: break;                                                  /* Initialize / Finalize */
    default: pthread_mutex_unlock(&ldn_lock); ipc_unimplemented(s, rq);
    }
    pthread_mutex_unlock(&ldn_lock);
}
static void ldn_creator(IpcSession *s, const IpcRequest *rq, IpcResponse *rs, int system) {
    switch (rq->cmd) {
    case 0:                                                                     /* Create{User,System}LocalCommunicationService */
        new_object(rs, system ? "ISystemLocalCommunicationService" : "IUserLocalCommunicationService", system ? ldn_system : ldn_user,
                   NULL, ldn_close);
        return;
    case 1: new_object(rs, "IClientProcessMonitor", ldn_client_monitor, NULL, NULL); return;   /* CreateClientProcessMonitor [18.0.0+] */
    default: ipc_unimplemented(s, rq);
    }
}
static void ldn_user_creator(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) { ldn_creator(s, rq, rs, 0); }
static void ldn_system_creator(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) { ldn_creator(s, rq, rs, 1); }
static void ldn_monitor_creator(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {
    if (rq->cmd != 0) ipc_unimplemented(s, rq);
    new_object(rs, "IMonitorService", ldn_monitor, NULL, NULL);                 /* CreateMonitorService */
}

/* ---------- nim:eca, nim:ecas: nn::ec::ShopServiceAccessor's service, offline (switchbrew "NIM services") ----------
   IShopServiceAccessServerInterface -> IShopServiceAccessServer -> IShopServiceAccessor -> IShopServiceAsync. Switchbrew
   gives the command numbers, not their arguments; the objects are made as asked (inputs ignored) and every request then
   fails the way a Switch without a connection fails it: 2164-0056 ResultInternetRequestNotAccepted, which needs no output
   layout. CreateAsyncInterface returns its event (signalled: the request is over at once) with the object. TODO(mac): its
   handle is not on switchbrew (docs/SERVICOS_NUVEM.md); the boot log shows each command FC 26 sends. */
static void shop_async(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {   /* IShopServiceAsync */
    switch (rq->cmd) {
    case 0: return;                                                             /* Cancel */
    case 4:                                                                     /* Request: accepted, ends at once in failure */
        fprintf(stderr, "[totk-net] shop request (nim:eca IShopServiceAsync) fails: offline, result %#x\n", EC_INTERNET_NOT_ACCEPTED);
        return;
    case 1: case 2: case 3: case 5:                                             /* GetSize, Read, GetErrorCode, Prepare */
        rs->result = EC_INTERNET_NOT_ACCEPTED; return;
    default: ipc_unimplemented(s, rq);
    }
}
static void shop_accessor(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {   /* IShopServiceAccessor */
    if (rq->cmd != 0) ipc_unimplemented(s, rq);                                 /* CreateAsyncInterface */
    uint32_t event = runtime_event_new();
    runtime_event_signal(event);
    rs->copy[rs->ncopy++] = runtime_event_readable(event);
    new_object(rs, "IShopServiceAsync", shop_async, NULL, NULL);
}
static void shop_server(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {   /* IShopServiceAccessServer */
    if (rq->cmd != 0) ipc_unimplemented(s, rq);                                 /* CreateAccessorInterface */
    new_object(rs, "IShopServiceAccessor", shop_accessor, NULL, NULL);
}
static void nim_eca(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {     /* IShopServiceAccessServerInterface */
    switch (rq->cmd) {
    case 0: case 5: new_object(rs, "IShopServiceAccessServer", shop_server, NULL, NULL); return;   /* CreateServerInterface(2) */
    case 4: { uint8_t v = 0; IPC_OUT(rs, v); return; }                          /* IsLargeResourceAvailable: no */
    default: ipc_unimplemented(s, rq);                                          /* 1-3: debug responses */
    }
}
static void nim_ecas(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {    /* IShopServiceAccessSystemInterface */
    (void)rs;
    if (rq->cmd > 1) ipc_unimplemented(s, rq);                                  /* (Un)RegisterSpecialClient */
}

__attribute__((constructor)) static void register_offline_services(void) {
    runtime_ipc_register("aoc:u", aoc_handler, NULL, NULL);
    runtime_ipc_register("pctl", pctl_factory, NULL, NULL);
    runtime_ipc_register("pctl:a", pctl_factory, NULL, NULL);
    runtime_ipc_register("pctl:s", pctl_factory, NULL, NULL);
    runtime_ipc_register("pctl:r", pctl_factory, NULL, NULL);
    runtime_ipc_register("ldn:u", ldn_user_creator, NULL, NULL);
    runtime_ipc_register("ldn:s", ldn_system_creator, NULL, NULL);
    runtime_ipc_register("ldn:m", ldn_monitor_creator, NULL, NULL);
    runtime_ipc_register("nim:eca", nim_eca, NULL, NULL);
    runtime_ipc_register("nim:ecas", nim_ecas, NULL, NULL);
}
