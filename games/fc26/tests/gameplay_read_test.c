#include <stdint.h>
#include <sys/mman.h>
#include <assert.h>
#include "../runtime/gameplay_read.h"
int main(void) {
    size_t size=0xc712900;
    uint8_t *base=mmap(NULL,size,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);
    assert(base!=MAP_FAILED);
    uint8_t obj[256]={0}, regulator[64]={0}, before[256]; char name[160]="SyntheticFlag";
    uint64_t ptr=(uint64_t)obj; memcpy(base+0xc665768,&ptr,8);
    ptr=(uint64_t)regulator; memcpy(base+0xc712880,&ptr,8);
    for (unsigned i=0;i<78;i++) {
        uint64_t row[4]={(uint64_t)name,0,0x40+i,(uint64_t)base+0xcb8c6d0};
        memcpy(base+0xb7c3558+32*i,row,sizeof row); obj[0x40+i]=(i%2);
    }
    float sim=30,render=30; memcpy(regulator+0x20,&sim,4);memcpy(regulator+0x24,&render,4);
    memcpy(before,obj,sizeof obj);
    FILE *out=tmpfile(); assert(out);
    assert(fc26_gameplay_read(base,out)); assert(!memcmp(before,obj,sizeof obj));
    rewind(out); char line[512];unsigned n=0; while(fgets(line,sizeof line,out))n++;
    assert(n==80);
    ptr=1; memcpy(base+0xc665768,&ptr,8); assert(!fc26_gameplay_read(base,out));
    assert(!fc26_gameplay_read(NULL,out)); fclose(out); munmap(base,size);
    return 0;
}
