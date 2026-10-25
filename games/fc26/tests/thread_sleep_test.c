/* Compile the real implementation; observe timer flags and inject one EINTR. */
#include <sys/event.h>
#include <errno.h>
#include <fcntl.h>
static int timer_calls, interrupt_once, last_queue;
static int probe_kevent(int, const struct kevent *, int, struct kevent *, int, const struct timespec *);
#define kevent(...) probe_kevent(__VA_ARGS__)
#include "../runtime/threads.c"
#include <assert.h>

uint64_t runtime_now_ns(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000000000 + t.tv_nsec;
}
_Noreturn void runtime_fail(const char *s) { fprintf(stderr, "%s\n", s); abort(); }
void *runtime_symbol(const char *s) { (void)s; return NULL; }
void runtime_thread_init(void) {}
void dm_thread_enter(uint64_t a, uint64_t b, uint64_t c, uint64_t *d) {
    (void)a; (void)b; (void)c; (void)d; abort();
}
_Noreturn void runtime_thread_leave(const uint64_t *a, void *b, void (*c)(void *)) {
    (void)a; c(b); abort();
}
static int probe_kevent(int fd, const struct kevent *in, int ni,
                        struct kevent *out, int no, const struct timespec *timeout) {
    assert(ni == 1 && no == 1 && in->filter == EVFILT_TIMER);
    assert((in->fflags & (NOTE_NSECONDS | NOTE_CRITICAL)) == (NOTE_NSECONDS | NOTE_CRITICAL));
    assert(in->flags & EV_ONESHOT);
    timer_calls++; last_queue = fd;
    if (interrupt_once) { interrupt_once = 0; errno = EINTR; return -1; }
    return (kevent)(fd, in, ni, out, no, timeout);
}
static void *sleeper(void *arg) { (void)arg; host_sleep_ns(1000000); return NULL; }
int main(void) {
    pthread_set_qos_class_self_np(QOS_CLASS_USER_INTERACTIVE, 0);
    host_sleep_ns(0); host_sleep_ns(-1); assert(timer_calls == 0);
    interrupt_once = 1;
    uint64_t start = runtime_now_ns();
    for (int i = 0; i < 100; i++) host_sleep_ns(1000000);
    uint64_t elapsed = runtime_now_ns() - start;
    fprintf(stderr, "100 sleeps of 1ms: %.3fms\n", elapsed / 1e6);
    assert(elapsed >= 100000000 && elapsed < 250000000);
    assert(timer_calls >= 101 && !interrupt_once);
    int main_queue = last_queue;
    assert(fcntl(main_queue, F_GETFD) >= 0);
    pthread_t thread; assert(!pthread_create(&thread, NULL, sleeper, NULL));
    assert(!pthread_join(thread, NULL));
    assert(last_queue != main_queue);
    errno = 0; assert(fcntl(last_queue, F_GETFD) == -1 && errno == EBADF);
    assert(fcntl(main_queue, F_GETFD) >= 0);
    /* The diagnostic is inert without profiling; production keeps all timers critical. */
    assert(!runtime_timer_diagnostic_limit(16000000));
    thread_profile_on=1;
    assert(runtime_timer_diagnostic_limit(16000000));
    assert(timer_wait_flags(1000000)&NOTE_CRITICAL);
    assert(timer_wait_flags(16000000)&NOTE_CRITICAL);
    assert(!(timer_wait_flags(100000000)&NOTE_CRITICAL));
    assert(atomic_load(&timer_noncritical)==1);
    assert(runtime_timer_diagnostic_limit(0));
    assert(timer_wait_flags(100000000)&NOTE_CRITICAL);
    thread_profile_on=0;
    return 0;
}
