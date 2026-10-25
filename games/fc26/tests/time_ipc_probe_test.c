/* Real IPC clock handlers feed the same optional probe as direct SDK clocks. */
#include "../runtime/time_probe.c"
#include "../runtime/ipc.h"
#include <time.h>
/*CLOCK_HANDLERS*/
#include <assert.h>
uint64_t runtime_now_ns(void) {return 1234567890;}
void ipc_out(IpcResponse *rs,const void *data,unsigned n) {(void)rs;(void)data;(void)n;}
_Noreturn void ipc_unimplemented(const IpcSession *s,const IpcRequest *rq) {(void)s;(void)rq;abort();}
int main(void) {
    IpcRequest rq={0};IpcResponse rs={0};
    fc26_time_probe_on=1;
    clock_handler(NULL,&rq,&rs);
    assert(atomic_load(&calls[FC_CLOCK_IPC_SYSTEM_SEC])==1);
    assert(atomic_load(&last[FC_CLOCK_IPC_SYSTEM_SEC])>1000000000);
    memset(&rs,0,sizeof rs);
    steady_clock_handler(NULL,&rq,&rs);
    assert(atomic_load(&calls[FC_CLOCK_IPC_STEADY_SEC])==1);
    fc26_time_probe_on=0;
    clock_handler(NULL,&rq,&rs);
    assert(atomic_load(&calls[FC_CLOCK_IPC_SYSTEM_SEC])==1);
    return 0;
}
