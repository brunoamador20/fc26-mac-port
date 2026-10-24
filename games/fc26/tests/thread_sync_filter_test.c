#include "../runtime/threads.c"
#include <assert.h>
uint64_t runtime_now_ns(void){ struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (uint64_t)t.tv_sec*1000000000+t.tv_nsec; }
_Noreturn void runtime_fail(const char *s){fprintf(stderr,"%s\n",s);abort();}
void *runtime_symbol(const char *s){(void)s;return NULL;}
void runtime_thread_init(void){}
void dm_thread_enter(uint64_t a,uint64_t b,uint64_t c,uint64_t*d){(void)a;(void)b;(void)c;(void)d;abort();}
_Noreturn void runtime_thread_leave(const uint64_t*a,void*b,void(*c)(void*)){(void)a;c(b);abort();}
int main(void) {
    uint32_t ha=runtime_event_new(),hb=runtime_event_new();
    uint32_t ra=runtime_event_readable(ha),rb=runtime_event_readable(hb);
    thr_t a={.cur_core=-1,.wkind=4,.nwh=1,.wh={ra}},b={.cur_core=-1,.wkind=4,.nwh=1,.wh={rb}};
    pthread_cond_init(&a.cv,NULL);pthread_cond_init(&b.cv,NULL);
    profile_lock();a.next=&b;g_wait=&a;profile_unlock();
    runtime_event_signal(ha);
    assert(a.woke && !a.wkind);
    assert(!b.woke && b.wkind==4); /* unrelated event must not reacquire a core */
    runtime_event_signal(hb);assert(b.woke && !g_wait);
    /* A matching object can be at the last legal index, beyond dump's four. */
    profile_lock();
    ((event_t *)h_peek(ha,O_EVENT_W))->signaled=0;
    ((event_t *)h_peek(hb,O_EVENT_W))->signaled=0;
    thr_t c={.cur_core=-1,.wkind=4,.nwh=64},z={.cur_core=-1,.wkind=4,.nwh=0};
    pthread_cond_init(&c.cv,NULL);pthread_cond_init(&z.cv,NULL);
    for(int i=0;i<64;i++)c.wh[i]=rb;c.wh[63]=ra;
    c.next=&z;g_wait=&c;profile_unlock();
    runtime_event_signal(ha);assert(c.woke && !z.woke && g_wait==&z);
    profile_lock();z.cancel=1;profile_unlock();
    runtime_event_signal(hb);assert(z.woke && !g_wait);
    /* A handle closed while waiting must wake the waiter to report an error. */
    profile_lock();b.woke=0;b.wkind=4;b.next=NULL;g_wait=&b;
    g_h[rb-0x1000].type=O_FREE;profile_unlock();
    runtime_event_signal(ha);assert(b.woke && !g_wait);
    pthread_cond_destroy(&a.cv);pthread_cond_destroy(&b.cv);
    pthread_cond_destroy(&c.cv);pthread_cond_destroy(&z.cv);return 0;
}
