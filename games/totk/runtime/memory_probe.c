/* Validate stack moves and logical accounting using the production SVC path. */
#include "runtime.h"
#include <stdio.h>
#include <string.h>
static void call(unsigned n,uint64_t *r){runtime_svc(n,r,"memory-probe",0);}
static void check(int ok,const char *s){if(!ok)runtime_fail(s);}
void runtime_memory_probe(void){
 runtime_thread_init();svc_thread_main_init();
 uint64_t r[31]={0};r[1]=14;call(0x29,r);uint64_t dst=r[1]+0x13000;
 r[1]=0x200000;call(1,r);check(!r[0],"probe heap");uint8_t *src=(void *)(uintptr_t)(r[1]+0x13000);
 for(unsigned i=0;i<0x10000;i++)src[i]=(unsigned char)(i*13+7);
 r[0]=dst;r[1]=(uintptr_t)src;r[2]=0x10000;call(4,r);check(!r[0],"map stack");
 for(unsigned i=0;i<0x10000;i++)check(((unsigned char *)(uintptr_t)dst)[i]==(unsigned char)(i*13+7),"mapped stack content");
 struct{uint64_t base,size;uint32_t state,attr,perm,ipc,device,pad;} info;
 r[0]=(uintptr_t)&info;r[2]=dst+0x5000;call(6,r);check(info.base==dst&&info.size==0x10000&&info.state==0xb&&info.perm==3,"mapped stack query");
 r[0]=(uintptr_t)&info;r[2]=(uintptr_t)src+0x5000;call(6,r);check(info.base==(uintptr_t)src&&info.size==0x10000&&info.state==5&&info.perm==0&&info.attr==4,"moved source accounting");
 r[0]=dst;r[1]=(uintptr_t)src;r[2]=0x10000;call(4,r);check(r[0]!=0,"duplicate mapping rejected");
 memset((void *)(uintptr_t)dst,0x5a,0x10000);r[0]=dst;r[1]=(uintptr_t)src;r[2]=0x10000;call(5,r);check(!r[0],"unmap stack");
 for(unsigned i=0;i<0x10000;i++)check(src[i]==0x5a,"unmap copy back");
 r[0]=(uintptr_t)&info;r[2]=dst;call(6,r);check(info.state==0&&info.perm==0,"unmapped stack query");
 r[0]=dst;r[1]=(uintptr_t)src;r[2]=0x10000;call(5,r);check(r[0]!=0,"second unmap rejected");
 r[1]=2;call(0x29,r);uint64_t alias=r[1]+0x1000;
 r[0]=alias;r[1]=0x1000;call(0x2c,r);check(!r[0],"alias page allocation");memset((void *)(uintptr_t)alias,0x37,4096);
 r[0]=alias+4096;r[1]=4096;call(0x2c,r);check(!r[0],"neighbor alias allocation");
 for(unsigned i=0;i<4096;i++)check(((unsigned char *)(uintptr_t)alias)[i]==0x37,"neighbor mapping preserves bytes");
 r[0]=alias;r[1]=4096;call(0x2d,r);check(!r[0],"alias partial unmap");
 r[0]=alias;r[1]=4096;call(0x2c,r);check(!r[0],"alias remap");for(unsigned i=0;i<4096;i++)check(((unsigned char *)(uintptr_t)alias)[i]==0,"reallocated alias zero fill");
 r[0]=(uintptr_t)&info;r[2]=alias;call(6,r);check(info.state==5&&info.perm==3,"alias allocation query");
 /* Horizon: MapPhysicalMemory over an already-mapped page succeeds and leaves that page untouched */
 ((unsigned char *)(uintptr_t)alias)[7]=0x5a;r[0]=alias;r[1]=4096;call(0x2c,r);check(!r[0],"duplicate physical map accepted");check(((unsigned char *)(uintptr_t)alias)[7]==0x5a,"duplicate physical map keeps contents");
 /* Reject an over-budget request before changing any page/accounting state,
    then show a smaller allocation can still succeed at the rejected address. */
 r[1]=6;call(0x29,r);uint64_t pool=r[1];r[1]=7;call(0x29,r);uint64_t used=r[1];
 check(pool>used,"memory probe requires free application pool");
 uint64_t rejected=alias+0x1000000,too_large=((pool-used)&~4095ULL)+4096;
 r[0]=rejected;r[1]=too_large;call(0x2c,r);check(r[0]==0x10801,"physical memory exhaustion must return LimitReached");
 r[1]=7;call(0x29,r);check(r[1]==used,"failed physical map changed accounting");
 r[0]=(uintptr_t)&info;r[2]=rejected;call(6,r);check(info.state==0&&info.perm==0,"failed physical map changed page state");
 check(((unsigned char *)(uintptr_t)alias)[7]==0x5a,"failed physical map changed existing contents");
 r[0]=rejected;r[1]=4096;call(0x2c,r);check(!r[0],"smaller allocation after exhausted request");
 r[0]=rejected;r[1]=4096;call(0x2d,r);check(!r[0],"release recovery allocation");
 r[1]=7;call(0x29,r);check(r[1]==used,"recovered physical map accounting");
 r[0]=alias+4096;r[1]=4096;call(0x2d,r);check(!r[0],"alias free tail");
 r[0]=alias;r[1]=8192;call(0x2d,r);check(!r[0],"alias complete unmap covering free hole");
 puts("{\"status\":\"pass\",\"scope\":\"64 KiB stack move/copyback, alias neighbor preservation and zero-fill remap, logical states, duplicate map/unmap rejection; host protection remains 16 KiB granular\"}");
}
