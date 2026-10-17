/* Host-thread and kernel synchronization tests, using the production dispatcher. */
#include "../runtime/runtime.h"
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <mach/mach_time.h>
static atomic_uint calls,environments;
_Noreturn void runtime_fail(const char *message){fprintf(stderr,"FAIL %s\n",message);exit(1);}
void *runtime_symbol(const char *name){(void)name;runtime_fail("unexpected guest symbol");}
void runtime_thread_init(void){atomic_fetch_add(&environments,1);}
uint64_t runtime_now_ns(void){mach_timebase_info_data_t t;mach_timebase_info(&t);return (uint64_t)((__uint128_t)mach_absolute_time()*t.numer/t.denom);}
static void need(int c,const char *m){if(!c)runtime_fail(m);}
static void kernel(unsigned id,uint64_t *r){need(svc_thread((int)id,r)==1,"service dispatch");}
static void child(uint64_t arg){atomic_fetch_add(&calls,1);uint64_t r[31]={arg};kernel(0x11,r);need(r[0]==0,"child signal");kernel(0x0a,r);runtime_fail("ExitThread returned");}
int main(void){
 uint32_t main=svc_thread_main_init();uint64_t r[31]={0};r[1]=main;kernel(0xc,r);need(r[0]==0&&r[1]==44,"initial priority");
 r[0]=main;r[1]=31;kernel(0xd,r);r[1]=main;kernel(0xc,r);need(r[0]==0&&r[1]==31,"priority roundtrip");
 r[1]=7;kernel(0xc,r);need(r[0]==0xe401,"bad handle query");r[0]=7;kernel(0x16,r);need(r[0]==0xe401,"bad handle close");
 unsigned count=0;
 for(unsigned i=0;i<32;i++){
  kernel(0x45,r);need(!r[0],"event create");uint32_t write=(uint32_t)r[1],read=(uint32_t)r[2];
  r[0]=read;kernel(0x11,r);need(r[0]==0xe401,"reject signaling read handle");
  r[1]=(uintptr_t)&read;r[2]=1;r[3]=0;kernel(0x18,r);need(r[0]==0xea01,"unsignaled event timeout");
  uint8_t *stack=mmap(NULL,2<<20,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);need(stack!=MAP_FAILED,"guest stack");
  r[1]=(uintptr_t)child;r[2]=write;r[3]=(uintptr_t)stack+(2<<20);r[4]=44;r[5]=0;kernel(8,r);need(!r[0],"thread create");uint32_t thread=(uint32_t)r[1];
  unsigned before=atomic_load(&calls);r[0]=thread;kernel(9,r);need(!r[0],"thread start");
  r[1]=(uintptr_t)&read;r[2]=1;r[3]=1000000000;kernel(0x18,r);need(!r[0]&&r[1]==0,"event wait");
  r[1]=(uintptr_t)&thread;r[2]=1;r[3]=1000000000;kernel(0x18,r);need(!r[0],"wait thread exit");need(atomic_load(&calls)==before+1,"child ran exactly once");
  r[0]=read;kernel(0x17,r);need(!r[0],"event reset");r[0]=read;kernel(0x17,r);need(r[0]==0xfa01,"second reset fails");
  r[0]=thread;kernel(0x16,r);need(!r[0],"close thread");r[0]=read;kernel(0x16,r);need(!r[0],"close read");r[0]=write;kernel(0x16,r);need(!r[0],"close write");
  need(munmap(stack,2<<20)==0,"reclaim guest stack after exit wait");
  count++;
 }
 need(atomic_load(&environments)==32,"per-thread setup");
 printf("{\"status\":\"pass\",\"native_threads\":%u,\"events\":%u,\"scope\":\"production SVC dispatcher, host stack switching, event/thread waits, priority and invalid handles\"}\n",count,count);return 0;
}
