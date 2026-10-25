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
    FILE *writes=tmpfile(); assert(writes);
    assert(fc26_gameplay_set(base,writes,"SyntheticFlag","1"));
    assert(obj[0x40]==1 && obj[0x41]==1);
    memcpy(before,obj,sizeof obj);
    const char *bad[]={"2","1.0","-1","true","1junk",""};
    for(unsigned i=0;i<sizeof bad/sizeof *bad;i++) {
        assert(!fc26_gameplay_set(base,writes,"SyntheticFlag",bad[i]));
        assert(!memcmp(before,obj,sizeof obj));
    }
    assert(!fc26_gameplay_set(base,writes,"Missing","1"));
    assert(!fc26_gameplay_set(base,writes,"DeltaTicks","1"));
    assert(!fc26_gameplay_set(base,writes,"Gen","1"));
    assert(!memcmp(before,obj,sizeof obj));
    uint64_t *row=(uint64_t *)(base+0xb7c3558);
    row[3]=(uint64_t)base+0xcb889a0; row[2]=0x30;
    assert(fc26_gameplay_set(base,writes,"SyntheticFlag","42"));
    uint32_t integer=0; memcpy(&integer,obj+0x30,4); assert(integer==42);
    assert(!fc26_gameplay_set(base,writes,"SyntheticFlag","4294967296"));
    memcpy(&integer,obj+0x30,4); assert(integer==42);
    assert(!fc26_gameplay_set(base,writes,"SyntheticFlag","2147483648"));
    assert(!fc26_gameplay_set(base,writes,"SyntheticFlag","-2147483649"));
    assert(fc26_gameplay_set(base,writes,"SyntheticFlag","-2147483648"));
    int32_t signed_integer=0; memcpy(&signed_integer,obj+0x30,4); assert(signed_integer==INT32_MIN);
    assert(fc26_gameplay_set(base,writes,"SyntheticFlag","2147483647"));
    memcpy(&signed_integer,obj+0x30,4); assert(signed_integer==INT32_MAX);
    assert(fc26_gameplay_set(base,writes,"SyntheticFlag","-42"));
    memcpy(&signed_integer,obj+0x30,4); assert(signed_integer==-42);
    row[3]=(uint64_t)base+0xcb8c6b0;
    assert(fc26_gameplay_set(base,writes,"SyntheticFlag","1.25"));
    float number=0; memcpy(&number,obj+0x30,4); assert(number==1.25f);
    assert(!fc26_gameplay_set(base,writes,"SyntheticFlag","nan"));
    assert(!fc26_gameplay_set(base,writes,"SyntheticFlag","inf"));
    assert(!fc26_gameplay_set(base,writes,"SyntheticFlag","1e100"));
    memcpy(&number,obj+0x30,4); assert(number==1.25f);
    row[3]=(uint64_t)base+0x1234;
    assert(!fc26_gameplay_set(base,writes,"SyntheticFlag","1"));
    assert(!fc26_gameplay_set(NULL,writes,"SyntheticFlag","1"));
    row[3]=(uint64_t)base+0xcb889a0; row[2]=0x24;
    assert(!fc26_gameplay_set(base,writes,"SyntheticFlag","1"));
    row[2]=0x20;
    assert(!fc26_gameplay_set(base,writes,"SyntheticFlag","1"));
    row[3]=(uint64_t)base+0xcb8c6d0; row[2]=0x40;
    fclose(writes);
    float sim=30,render=30; memcpy(regulator+0x20,&sim,4);memcpy(regulator+0x24,&render,4);
    memcpy(before,obj,sizeof obj);
    FILE *out=tmpfile(); assert(out);
    assert(fc26_gameplay_read(base,out)); assert(!memcmp(before,obj,sizeof obj));
    rewind(out); char line[512];unsigned n=0; while(fgets(line,sizeof line,out))n++;
    assert(n==80);
    fclose(out); out=tmpfile(); assert(out);
    ptr=0; memcpy(base+0xc712880,&ptr,8);
    assert(!fc26_gameplay_read(base,out));
    rewind(out); n=0; while(fgets(line,sizeof line,out))n++;
    /* A missing regulator must not suppress the 78 independent gameplay reads. */
    assert(n==80);
    ptr=1; memcpy(base+0xc665768,&ptr,8); assert(!fc26_gameplay_read(base,out));
    assert(!fc26_gameplay_set(base,out,"SyntheticFlag","1"));
    assert(!fc26_gameplay_read(NULL,out)); fclose(out); munmap(base,size);
    return 0;
}
