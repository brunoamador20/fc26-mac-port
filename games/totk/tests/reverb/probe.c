#include "audio_reverb.h"
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <math.h>
#include <string.h>
_Noreturn void runtime_fail(const char *msg) { fprintf(stderr,"%s\n",msg); exit(1); }
int main(int argc,char **argv) {
    if(argc!=2)return 2; FILE *f=fopen(argv[1],"rb");if(!f)return 2;
    const int cc[]={1,2,4,6}; unsigned checked=0; double worst=0;
    for(int test=0;test<4;test++){
        Reverb3dParam p={.channels=cc[test],.channel_max=6,.sample_rate=48000,.room_hf=-2000,.hf_reference=4000,.decay_time=.8f,.hf_decay_ratio=.7f,.room_gain=-800,.reflections_gain=0,.reverb_gain=500,.diffusion=50,.reflection_delay=.012f,.reverb_delay=.018f,.density=70,.dry_gain=.25f};
        Reverb3d *s=audio_reverb_create(&p);float in[6][240],out[6][240],*ip[6],*op[6]; for(int c=0;c<6;c++){ip[c]=in[c];op[c]=out[c];}
        for(int b=0;b<300;b++){
            if(b==70){p.density=30;p.room_hf=-500;p.dry_gain=.1f;audio_reverb_update(s,&p);}
            if(b==200){audio_reverb_free(s);s=audio_reverb_create(&p);}
            memset(out,0,sizeof out);
            for(int c=0;c<p.channels;c++)for(int k=0;k<240;k++){int t=b*240+k;in[c][k]=t%701==c*73?.125f:t<18000?((t*17+c*31)%257-128)/8192.f:0;}
            audio_reverb_process(s,ip,op,240);
            for(int c=0;c<p.channels;c++)for(int k=0;k<240;k++){
                float want;if(fread(&want,4,1,f)!=1)return 2;float got=out[c][k];if(getenv("TOTK_REVERB_NEGATIVE"))got=in[c][k];
                double err=fabs(got-want);if(err>worst)worst=err;
                if(!isfinite(got)||err>2e-6+fabs(want)*3e-4){fprintf(stderr,"channels=%d block=%d c=%d sample=%d got=%.9g want=%.9g error=%g\n",p.channels,b,c,k,got,want,err);return 1;}checked++;
            }
        }audio_reverb_free(s);
    }
    if(fgetc(f)!=EOF)return 2;fclose(f);printf("reverb reference: %u samples passed, max error %.9g\n",checked,worst);return 0;
}
