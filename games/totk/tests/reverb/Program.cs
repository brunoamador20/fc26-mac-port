using System;
using System.IO;
using System.Runtime.InteropServices;
using Ryujinx.Audio.Renderer.Parameter;
using Ryujinx.Audio.Renderer.Server.Effect;
using Ryujinx.Audio.Renderer.Dsp.Command;
using Ryujinx.Audio.Renderer.Dsp.State;
using Ryujinx.Audio.Renderer.Parameter.Effect;
class Program {
    const int N=240, Blocks=300;
    static void Main(string[] args) {
        if(args.Length>1) Limiter(args[1]);
        using var writer=new BinaryWriter(File.Create(args[0]));
        foreach(ushort channels in new ushort[]{1,2,4,6}) {
            var p=new Reverb3dParameter {ChannelCount=channels,ChannelCountMax=6,SampleRate=48000,RoomHf=-2000,HfReference=4000,DecayTime=.8f,HfDecayRatio=.7f,RoomGain=-800,ReflectionsGain=0,ReverbGain=500,Diffusion=50,ReflectionDelay=.012f,ReverbDelayTime=.018f,Density=70,DryGain=.25f};
            for(int c=0;c<channels;c++){p.Input[c]=(byte)c;p.Output[c]=(byte)(c+6);}
            var state=new Reverb3dState(ref p,0); var buffers=new float[12*N];
            using var ctx=new CommandList(null,buffers,N,48000,12,0);
            var cmd=new Reverb3dCommand().Initialize(0,p,new Reverb3dState[]{state},true,0,0,false);
            for(int b=0;b<Blocks;b++) {
                if(b==70){p.Density=30;p.RoomHf=-500;p.DryGain=.1f;state.UpdateParameter(ref p);cmd.Initialize(0,p,new Reverb3dState[]{state},true,0,0,false);}
                if(b==200){state=new Reverb3dState(ref p,0);cmd.Initialize(0,p,new Reverb3dState[]{state},true,0,0,false);}
                Array.Clear(buffers);
                for(int c=0;c<channels;c++)for(int k=0;k<N;k++){int t=b*N+k; buffers[c*N+k]=t%701==c*73?.125f: t<18000?((t*17+c*31)%257-128)/8192f:0;}
                cmd.ProcessReverb3d(ctx,ref state);
                for(int c=0;c<channels;c++)for(int k=0;k<N;k++)writer.Write(buffers[(6+c)*N+k]);
            }
        }
    }
    static void Limiter(string path) {
        using var writer=new BinaryWriter(File.Create(path));
        var p=new LimiterParameter{ChannelCount=2,ChannelCountMax=6,SampleRate=48000,AttackCoefficient=.2f,ReleaseCoefficient=.02f,Threshold=.5f,InputGain=1.3f,OutputGain=.8f,DelayBufferSampleCountMin=9,DelayBufferSampleCountMax=13,StatisticsEnabled=true,Status=UsageState.Enabled};
        p.Input[0]=0;p.Input[1]=1;p.Output[0]=0;p.Output[1]=1;
        var state=new LimiterState[]{new LimiterState(ref p,0)}; var result=new EffectResultState[1];
        ref var stats=ref MemoryMarshal.Cast<byte,LimiterStatistics>(result[0].SpecificData)[0];stats.Reset();
        var buffer=new float[N*2]; using var ctx=new CommandList(null,buffer,N,48000,2,0); var cmd=new LimiterCommandVersion2();
        for(int b=0;b<150;b++) {
            if(b==70){p.Threshold=.3f;p.AttackCoefficient=.4f;}
            if(b==120){state[0]=new LimiterState(ref p,0);stats.Reset();}
            p.StatisticsReset=b==50;
            for(int c=0;c<2;c++)for(int k=0;k<N;k++){int t=b*N+k;float x=((t*17+c*31)%257-128)/128f*(b%7==0?1.8f:.3f);buffer[c*N+k]=x*32768;}
            cmd.Initialize(0,p,state,result,b<100||b>=110,0,0).Process(ctx);
            for(int k=0;k<N;k++)for(int c=0;c<2;c++)writer.Write(Math.Clamp(buffer[c*N+k]/32768,-1,1));
            for(int c=0;c<6;c++)writer.Write(stats.InputMax[c]);for(int c=0;c<6;c++)writer.Write(stats.CompressionGainMin[c]);
        }
    }

}
