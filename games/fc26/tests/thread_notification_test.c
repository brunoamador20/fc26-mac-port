/* Service queue + kernel event + WaitSynchronization, all real implementations. */
#include "../runtime/threads.c"
#include "../runtime/applet_host.c"
#include <assert.h>
#include <stdatomic.h>
uint64_t runtime_now_ns(void) { return clock_gettime_nsec_np(CLOCK_MONOTONIC); }
_Noreturn void runtime_fail(const char *s) { fprintf(stderr,"%s\n",s);abort(); }
static uint32_t create_event(void *event,int autoclear,int inter_process) {
    (void)autoclear;assert(inter_process);
    uint32_t wh=runtime_event_new(),rh=runtime_event_readable(wh);
    memset(event,0,64);memcpy((char *)event+0x14,&wh,4);memcpy((char *)event+0x18,&rh,4);
    return 0;
}
static uint32_t writable(const void *event) { uint32_t h;memcpy(&h,(const char *)event+0x14,4);return h; }
static uint32_t readable(const void *event) { uint32_t h;memcpy(&h,(const char *)event+0x18,4);return h; }
void *runtime_symbol(const char *s) {
    if(strstr(s,"CreateSystemEvent"))return create_event;
    if(strstr(s,"GetWritableHandleOfSystemEvent"))return writable;
    if(strstr(s,"GetReadableHandleOfSystemEvent"))return readable;
    return NULL;
}
void runtime_thread_init(void) {}
void dm_thread_enter(uint64_t a,uint64_t b,uint64_t c,uint64_t*d) { (void)a;(void)b;(void)c;(void)d;abort(); }
_Noreturn void runtime_thread_leave(const uint64_t*a,void*b,void(*c)(void*)) { (void)a;c(b);abort(); }
static int ready(void *event) {
    uint32_t handle=readable(event);
    uint64_t regs[32]={0,(uintptr_t)&handle,1,0};
    assert(svc_thread(0x18,regs));
    assert(regs[0]==0 || regs[0]==R_TIMEOUT);
    return regs[0]==0;
}
static _Atomic unsigned ack;
static void *producer(void *unused) {
    (void)unused;
    for(unsigned i=1;i<=500;i++) {
        while(atomic_load(&ack)<i-1) sched_yield();
        runtime_oe_push_message(i);
    }
    return NULL;
}
int main(void) {
    pthread_key_t sdk_tls;assert(!pthread_key_create(&sdk_tls,NULL));
    svc_thread_main_init();
    void *event=get_notification_message_event();assert(!ready(event));
    runtime_oe_push_message(15);runtime_oe_push_message(16);assert(ready(event));
    uint32_t out=0;assert(try_pop(&out) && out==15);assert(ready(event));
    assert(try_pop(&out) && out==16);
    /* The drained service must stop making the SDK's WaitAny return at once. */
    assert(!ready(event));
    assert(!try_pop(&out));assert(!ready(event));
    runtime_oe_push_message(17);assert(ready(event));assert(pop()==17);assert(!ready(event));
    for(unsigned i=0;i<32;i++)runtime_oe_push_message(i);
    for(unsigned i=0;i<32;i++){assert(ready(event));assert(try_pop(&out) && out==i);}
    assert(!ready(event));
    pthread_t sender;assert(!pthread_create(&sender,NULL,producer,NULL));
    for(unsigned i=1;i<=500;i++) {
        while(!try_pop(&out)) sched_yield();
        assert(out==i && !ready(event));
        atomic_store(&ack,i);
    }
    assert(!pthread_join(sender,NULL));assert(!ready(event));
    return 0;
}
