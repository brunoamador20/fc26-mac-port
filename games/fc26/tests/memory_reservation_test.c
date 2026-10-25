/* Exercise memory_init itself with real Mach reservations, never overwrite a mapping. */
#include "../runtime/services.c"
void runtime_fail(const char *message) { fprintf(stderr, "FAIL: %s\n", message); exit(1); }
int main(int argc,char **argv) {
 (void)argv;
 const uint64_t gib=1ULL<<30, align=64ULL<<20, need=14ULL<<30;
 uint64_t prev=LOW_SEARCH_FROM, hole=0;
 while(prev<GUEST_ADDRESS_LIMIT) {
  mach_vm_address_t at=prev; mach_vm_size_t len=0;
  vm_region_basic_info_data_64_t info; mach_msg_type_number_t n=VM_REGION_BASIC_INFO_COUNT_64; mach_port_t obj=MACH_PORT_NULL;
  kern_return_t kr=mach_vm_region(mach_task_self(),&at,&len,VM_REGION_BASIC_INFO_64,(vm_region_info_t)&info,&n,&obj);
  if(obj!=MACH_PORT_NULL)mach_port_deallocate(mach_task_self(),obj);
  uint64_t end=kr==KERN_SUCCESS&&at<GUEST_ADDRESS_LIMIT?at:GUEST_ADDRESS_LIMIT;
  uint64_t start=(prev+align+align-1)&~(align-1);
  if(!(start&(gib-1)))start+=align;
  if(start+need+align<=end && !(start<=ALIAS_SPACE_AT&&ALIAS_SPACE_AT<start+need)) {hole=start;break;}
  if(kr!=KERN_SUCCESS||at+len<=prev)break;
  prev=at+len;
 }
 if(!hole){fprintf(stderr,"SKIP: no suitable free address gap for controlled fragmentation\n");return 77;}
 /* Every legacy 1-GiB candidate outside the chosen hole hits a guard or an existing mapping. */
 for(uint64_t at=LOW_SEARCH_FROM;at<GUEST_ADDRESS_LIMIT;at+=gib)
  if(at<hole || at>=hole+need)(void)reserve_fixed(at,(uint64_t)getpagesize());
 if(!reserve_fixed(hole-getpagesize(),getpagesize())||!reserve_fixed(hole+need,getpagesize()))return 2;
 if(argc==1)setenv("TOTK_ALIAS_GIB","8",1);else unsetenv("TOTK_ALIAS_GIB");
 fprintf(stderr,"controlled free hole %#llx..%#llx, 14 GiB, aligned to 64 MiB but not 1 GiB\n",(unsigned long long)hole,(unsigned long long)(hole+need));
 memory_init();
 if((uintptr_t)low_space!=hole || alias_space!=low_space+LOW_SIZE || ALIAS_SIZE!=(8ULL<<30) || (uintptr_t)alias_space+ALIAS_SIZE>GUEST_ADDRESS_LIMIT)return 3;
 fprintf(stderr,"PASS: real reservation found the controlled hole and preserved the guest layout\n");
 return 0;
}
