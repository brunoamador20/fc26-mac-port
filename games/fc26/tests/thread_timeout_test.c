/* Real block/core/wake functions, including a signal before kevent starts. */
#include <sys/event.h>
#include <stdatomic.h>
static _Atomic int phase, signalled, force_before_wait;
static int probe_kevent(int, const struct kevent *, int, struct kevent *, int, const struct timespec *);
#define kevent(...) probe_kevent(__VA_ARGS__)
#include "../runtime/threads.c"
#include <assert.h>
uint64_t runtime_now_ns(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t);
    return (uint64_t)t.tv_sec*1000000000+t.tv_nsec;
}
_Noreturn void runtime_fail(const char *s) { fprintf(stderr,"%s\n",s);abort(); }
void *runtime_symbol(const char *s) { (void)s;return NULL; }
void runtime_thread_init(void) {}
void dm_thread_enter(uint64_t a,uint64_t b,uint64_t c,uint64_t*d) { (void)a;(void)b;(void)c;(void)d;abort(); }
_Noreturn void runtime_thread_leave(const uint64_t*a,void*b,void(*c)(void*)) { (void)a;c(b);abort(); }
static int probe_kevent(int fd,const struct kevent *in,int ni,struct kevent *out,int no,const struct timespec *timeout) {
    if(ni && in->filter==EVFILT_TIMER && atomic_exchange(&force_before_wait,0))
        while(!atomic_load(&signalled)) sched_yield();
    return (kevent)(fd,in,ni,out,no,timeout);
}
static void *waker(void *arg) {
    thr_t *t=arg;
    thr_t other={.mask=1,.core=0,.cur_core=-1};
    for(int i=1;i<=200;i++) {
        while(atomic_load(&phase)<i) sched_yield();
        profile_lock();
        assert(t->wkind==2 && t->cur_core==-1);
        core_take(&other); assert(other.cur_core==0);core_put(&other);
        wake(t,0);profile_unlock();atomic_store(&signalled,i);
    }
    return NULL;
}
int main(void) {
    pthread_set_qos_class_self_np(QOS_CLASS_USER_INTERACTIVE,0);
    thr_t t={.mask=1,.core=0,.cur_core=-1};pthread_cond_init(&t.cv,NULL);
    uint64_t start=runtime_now_ns();
    profile_lock();core_take(&t);
    for(int i=0;i<100;i++) {
        assert(block(&t,2,1000000)==R_TIMEOUT);
        assert(t.cur_core==0 && g_core_owner[0]==&t);
    }
    core_put(&t);profile_unlock();
    uint64_t elapsed=runtime_now_ns()-start;
    fprintf(stderr,"100 real block(1ms) timeouts: %.3fms\n",elapsed/1e6);
    assert(elapsed>=100000000 && elapsed<250000000);
    pthread_t thread;assert(!pthread_create(&thread,NULL,waker,&t));
    atomic_store(&force_before_wait,1);
    for(int i=1;i<=200;i++) {
        profile_lock();core_take(&t);atomic_store(&phase,i);
        assert(block(&t,2,i<=100?1000000000:-1)==0);
        assert(t.cur_core==0 && g_core_owner[0]==&t);
        core_put(&t);profile_unlock();
    }
    assert(!pthread_join(thread,NULL));
    assert(!g_wait && !g_core_wait && !g_core_owner[0]);
    profile_lock();wait_queue_close(&t);profile_unlock();
    pthread_cond_destroy(&t.cv);return 0;
}
