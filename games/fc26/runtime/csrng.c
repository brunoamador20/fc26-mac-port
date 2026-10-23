/* csrng: nn::spl's cryptographically secure random number service (switchbrew "SPL services", csrng: command 0
   GenerateRandomBytes, one out buffer filled with random bytes). The sdk opens it through sm for nn::crypto's
   GenerateCryptographicallyRandomBytes; FC 26 does so when Career mode sets up its first match (boot car1, 2026-10-23:
   sm GetServiceHandle("csrng") from main+0x2a80eac stopped the runtime). The bytes come from the Mac's arc4random. */
#include "runtime.h"
#include "ipc.h"
#include <stdio.h>
#include <stdlib.h>

static void csrng_handler(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {
    switch (rq->cmd) {
    case 0: {                                                /* GenerateRandomBytes(out buffer) */
        if (rq->nb) { arc4random_buf(ipc_guest(rq->b[0].addr, rq->b[0].size), rq->b[0].size); return; }
        if (rq->nc) {                                        /* an auto-select buffer the client sent as a pointer */
            arc4random_buf(ipc_guest(rq->c[0].addr, rq->c[0].size), rq->c[0].size);
            rs->xout[rs->nxout++] = (IpcBuffer){rq->c[0].addr, rq->c[0].size, 0};
            return;
        }
        runtime_fail("csrng GenerateRandomBytes: no output buffer");
    }
    default: ipc_unimplemented(s, rq);
    }
}

__attribute__((constructor)) static void register_csrng(void) { runtime_ipc_register("csrng", csrng_handler, NULL, NULL); }
