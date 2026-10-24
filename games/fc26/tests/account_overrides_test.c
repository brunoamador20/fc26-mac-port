/* Synthetic test harness for nn::account overrides in FC 26 runtime:
   ListAllUsers, ListOpenUsers, IsNetworkServiceAccountAvailable,
   LoadNetworkServiceLicenseInfoAsync, ShowLicenseRequirementsForNetworkService,
   CreateNintendoAccountAuthorizationRequest, AsyncContext methods,
   NintendoAccountAuthorizationRequestContext methods. */
#include "runtime.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <unistd.h>
#include <sys/wait.h>
#include <stdbool.h>

/* Minimal stubs required to link account.c standalone */
static int g_event_signaled = 0;
void hle_clear_system_event(void *ev) { (void)ev; }
void hle_signal_system_event(void *ev) {
    if (ev) {
        ((uint8_t *)ev)[0x28] = 1;
        g_event_signaled = 1;
    }
}
void runtime_account_uid(uint64_t out[2]);

typedef struct { uint64_t lo, hi; } Uid;
typedef struct { Uid uid; uint64_t token; } UserHandle;

#define NSA_UNAVAILABLE ((uint32_t)124 | ((uint32_t)280 << 9)) /* 0x2307c */

int main(int argc, char **argv) {
    if (!getenv("TOTK_PROFILE_DIR")) setenv("TOTK_PROFILE_DIR", "/tmp/fc26_account_test_profile", 1);

    /* Child process test for GetNetworkServiceLicenseKind (must abort via runtime_fail) */
    if (argc > 1 && !strcmp(argv[1], "--child-license-kind")) {
        int (*get_license_kind)(void *) = (int (*)(void *))runtime_account_override("_ZN2nn7account37AsyncNetworkServiceLicenseInfoContext28GetNetworkServiceLicenseKindEv");
        if (!get_license_kind) exit(2);
        char dummy_ctx[64] = {0};
        get_license_kind(dummy_ctx);
        /* If we reach here, it failed to abort */
        exit(0);
    }

    /* Resolve overrides */
    void (*init)(void) = (void (*)(void))runtime_account_override("_ZN2nn7account10InitializeEv");
    assert(init != NULL);
    init();

    uint64_t me[2];
    runtime_account_uid(me);
    Uid local_uid = {me[0], me[1]};

    uint32_t (*open_user)(UserHandle *, const Uid *) = (uint32_t (*)(UserHandle *, const Uid *))runtime_account_override("_ZN2nn7account8OpenUserEPNS0_10UserHandleERKNS0_3UidE");
    void (*close_user)(const UserHandle *) = (void (*)(const UserHandle *))runtime_account_override("_ZN2nn7account9CloseUserERKNS0_10UserHandleE");
    unsigned (*preselected)(UserHandle *) = (unsigned (*)(UserHandle *))runtime_account_override("_ZN2nn7account22TryOpenPreselectedUserEPNS0_10UserHandleE");

    assert(open_user != NULL);
    assert(close_user != NULL);
    assert(preselected != NULL);

    /* 1. ListAllUsers */
    uint32_t (*list_all)(int *, Uid *, int) = (uint32_t (*)(int *, Uid *, int))runtime_account_override("_ZN2nn7account12ListAllUsersEPiPNS0_3UidEi");
    assert(list_all != NULL);

    assert(list_all(NULL, NULL, 0) == 0x7c67);
    int count = -1;
    assert(list_all(&count, NULL, 0) == 0);
    assert(count == 1);

    Uid all_users[4];
    memset(all_users, 0, sizeof(all_users));
    assert(list_all(&count, all_users, 4) == 0);
    assert(count == 1);
    assert(all_users[0].lo == local_uid.lo && all_users[0].hi == local_uid.hi);

    /* 2. ListOpenUsers & coherence with OpenUser / CloseUser */
    uint32_t (*list_open)(int *, Uid *, int) = (uint32_t (*)(int *, Uid *, int))runtime_account_override("_ZN2nn7account13ListOpenUsersEPiPNS0_3UidEi");
    assert(list_open != NULL);

    /* Initially no open users */
    assert(list_open(NULL, NULL, 0) == 0x7c67);
    count = -1;
    assert(list_open(&count, NULL, 0) == 0);
    assert(count == 0);

    /* Open user handle 1 */
    UserHandle h1 = {{0, 0}, 0};
    assert(open_user(&h1, &local_uid) == 0);
    assert(h1.token != 0);

    count = -1;
    memset(all_users, 0, sizeof(all_users));
    assert(list_open(&count, all_users, 4) == 0);
    assert(count == 1);
    assert(all_users[0].lo == local_uid.lo && all_users[0].hi == local_uid.hi);

    /* Open user handle 2 (multiple handles for the single user) */
    UserHandle h2 = {{0, 0}, 0};
    assert(preselected(&h2) == 1);
    assert(h2.token != 0);
    assert(h2.token != h1.token);

    count = -1;
    assert(list_open(&count, all_users, 4) == 0);
    assert(count == 1); /* Still 1 unique open user! */

    /* Close handle 1: handle 2 is still open */
    close_user(&h1);
    count = -1;
    assert(list_open(&count, all_users, 4) == 0);
    assert(count == 1);

    /* Close handle 2: now 0 open users */
    close_user(&h2);
    count = -1;
    assert(list_open(&count, all_users, 4) == 0);
    assert(count == 0);

    /* 3. IsNetworkServiceAccountAvailable */
    uint32_t (*is_nsa_avail)(bool *, const UserHandle *) = (uint32_t (*)(bool *, const UserHandle *))runtime_account_override("_ZN2nn7account32IsNetworkServiceAccountAvailableEPbRKNS0_10UserHandleE");
    assert(is_nsa_avail != NULL);

    /* Invalid handle returns error */
    bool avail = true;
    assert(is_nsa_avail(&avail, &h1) == 0x7c67);

    /* Valid open handle: network service account is unavailable */
    assert(open_user(&h1, &local_uid) == 0);
    assert(is_nsa_avail(NULL, &h1) == 0x7c67);
    assert(is_nsa_avail(&avail, &h1) == 0);
    assert(avail == false);

    /* 4. ShowLicenseRequirementsForNetworkService */
    void (*show_req)(const UserHandle *) = (void (*)(const UserHandle *))runtime_account_override("_ZN2nn7account40ShowLicenseRequirementsForNetworkServiceERKNS0_10UserHandleE");
    assert(show_req != NULL);
    show_req(&h1); /* Must not crash */

    /* 5. LoadNetworkServiceLicenseInfoAsync & AsyncContext */
    uint32_t (*load_license)(void *, const UserHandle *) = (uint32_t (*)(void *, const UserHandle *))runtime_account_override("_ZN2nn7account34LoadNetworkServiceLicenseInfoAsyncEPNS0_37AsyncNetworkServiceLicenseInfoContextERKNS0_10UserHandleE");
    uint32_t (*async_get_sys_event)(void *, void *) = (uint32_t (*)(void *, void *))runtime_account_override("_ZN2nn7account12AsyncContext14GetSystemEventEPNS_2os11SystemEventE");
    void (*async_cancel)(void *) = (void (*)(void *))runtime_account_override("_ZN2nn7account12AsyncContext6CancelEv");
    uint32_t (*async_has_done)(void *, bool *) = (uint32_t (*)(void *, bool *))runtime_account_override("_ZN2nn7account12AsyncContext7HasDoneEPb");
    uint32_t (*async_get_result)(void *) = (uint32_t (*)(void *))runtime_account_override("_ZN2nn7account12AsyncContext9GetResultEv");

    assert(load_license != NULL);
    assert(async_get_sys_event != NULL);
    assert(async_cancel != NULL);
    assert(async_has_done != NULL);
    assert(async_get_result != NULL);

    char async_ctx[64] = {0};
    assert(load_license(async_ctx, &h1) == 0);

    bool done = false;
    assert(async_has_done(async_ctx, &done) == 0);
    assert(done == true);

    uint32_t res = async_get_result(async_ctx);
    assert(res == NSA_UNAVAILABLE);

    char sys_event[64] = {0};
    g_event_signaled = 0;
    assert(async_get_sys_event(async_ctx, sys_event) == 0);
    assert(g_event_signaled == 1);

    async_cancel(async_ctx);

    /* 6. CreateNintendoAccountAuthorizationRequest & NintendoAccountAuthorizationRequestContext */
    uint32_t (*create_auth)(void *, const UserHandle *, const void *, void *, size_t) =
        (uint32_t (*)(void *, const UserHandle *, const void *, void *, size_t))runtime_account_override("_ZN2nn7account41CreateNintendoAccountAuthorizationRequestEPNS0_42NintendoAccountAuthorizationRequestContextERKNS0_10UserHandleERKNS0_45NintendoAccountAuthorizationRequestParametersEPvm");
    uint32_t (*auth_get_sys_event)(void *, void *) = (uint32_t (*)(void *, void *))runtime_account_override("_ZN2nn7account42NintendoAccountAuthorizationRequestContext14GetSystemEventEPNS_2os11SystemEventE");
    void (*auth_cancel)(void *) = (void (*)(void *))runtime_account_override("_ZN2nn7account42NintendoAccountAuthorizationRequestContext6CancelEv");
    uint32_t (*auth_get_result)(void *) = (uint32_t (*)(void *))runtime_account_override("_ZN2nn7account42NintendoAccountAuthorizationRequestContext34GetResultWithInteractionIfRequiredEv");
    uint32_t (*auth_get_code)(void *, size_t *, char *, size_t) = (uint32_t (*)(void *, size_t *, char *, size_t))runtime_account_override("_ZN2nn7account42NintendoAccountAuthorizationRequestContext20GetAuthorizationCodeEPmPcm");
    uint32_t (*auth_get_state)(void *, size_t *, char *, size_t) = (uint32_t (*)(void *, size_t *, char *, size_t))runtime_account_override("_ZN2nn7account42NintendoAccountAuthorizationRequestContext8GetStateEPmPcm");

    assert(create_auth != NULL);
    assert(auth_get_sys_event != NULL);
    assert(auth_cancel != NULL);
    assert(auth_get_result != NULL);
    assert(auth_get_code != NULL);
    assert(auth_get_state != NULL);

    char auth_ctx[64] = {0};
    assert(create_auth(auth_ctx, &h1, NULL, NULL, 0) == 0);

    assert(auth_get_result(auth_ctx) == NSA_UNAVAILABLE);

    size_t out_sz = 999;
    char code_buf[32] = {0};
    assert(auth_get_code(auth_ctx, &out_sz, code_buf, sizeof(code_buf)) == NSA_UNAVAILABLE);
    assert(out_sz == 0);

    out_sz = 999;
    char state_buf[32] = {0};
    assert(auth_get_state(auth_ctx, &out_sz, state_buf, sizeof(state_buf)) == NSA_UNAVAILABLE);
    assert(out_sz == 0);

    g_event_signaled = 0;
    assert(auth_get_sys_event(auth_ctx, sys_event) == 0);
    assert(g_event_signaled == 1);

    auth_cancel(auth_ctx);

    close_user(&h1);

    /* 7. Child process verification for GetNetworkServiceLicenseKind */
    pid_t pid = fork();
    if (pid == 0) {
        char *child_argv[] = { argv[0], "--child-license-kind", NULL };
        execv(argv[0], child_argv);
        exit(127);
    }
    int status = 0;
    waitpid(pid, &status, 0);
    assert(WIFEXITED(status));
    assert(WEXITSTATUS(status) == 1); /* exited via runtime_fail */

    printf("ALL_ACCOUNT_OVERRIDES_OK\n");
    return 0;
}
