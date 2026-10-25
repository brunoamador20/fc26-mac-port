#!/usr/bin/env python3
"""Rota conferida para boot_gpu.sh (macOS; Python com Pillow; tesseract local).
Fonte versionada: rev/nxport/tools/rota_robusta.py; tools/ pode ser um link.
Uso, na raiz: venv/bin/python tools/rota_robusta.py NOME --bin work/build-nxport/fc26-native [--fps60] [--profile]
O controlador inicia o boot, espera a trava e só assume o PID descendente dele.
Não inicia se já houver jogo aberto. Não compila nem altera build-update/app.
--wait-idle aguarda o jogo existente sair, sem enviar comandos.
--warm-timeout limita o aquecimento; --slot-timeout limita a espera da trava.
Fotos, OCR, referências e medições ficam em work/, fora do git. Cada transição
é confirmada por texto local e, quando disponível, pela região estável da
referência. Referências novas exigem o texto esperado; nunca aceitam uma tela
somente por tempo decorrido. A seleção de Pontapé usa também o brilho do texto.
Falha, sinal ou término sempre pedem close; após 15 s encerram apenas os PIDs
identificados como filhos deste controlador (incluindo filhos de lockf).
"""
import argparse, csv, io, json, os, re, signal, subprocess, sys, time, unicodedata
from pathlib import Path
from PIL import Image, ImageChops, ImageStat, ImageOps
ROOT = next(p for p in Path(__file__).resolve().parents if (p/'work').is_dir())
WORK = ROOT/'work'; LOGS = WORK/'logs'
EA_PATTERN = r'servidores.*\bea\b|\bea\b.*(servidores|indisponiv)|nao.*possivel.*(ligar|conectar|estabelecer)'
START_PATTERN = r'(prime|pressione|press).*qualquer.*(botao|button)'
def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s.lower()) if not unicodedata.combining(c))
def processes():
    out = subprocess.check_output(['ps','-axo','pid=,ppid=,command='], text=True)
    return {int(v[0]): (int(v[1]),v[2]) for line in out.splitlines() if len(v:=line.strip().split(None,2))==3}
def games():
    return {p for p,(_,c) in processes().items() if re.search(r'fc26-native rewritten/', c)}
class Route:
    def __init__(self,a):
        self.a=a; self.boot=None; self.pid=None; self.owned=set(); self.seq=0
        self.log=LOGS/f'boot_{a.name}.log'; self.inp=LOGS/f'input_{a.name}.txt'
        self.evidence=LOGS/f'{a.name}_route.jsonl'; self.refs=WORK/'rota-referencias'; self.refs.mkdir(exist_ok=True)
    def record(self,event,**kw):
        row=dict(time=time.time(), event=event, **kw)
        with self.evidence.open('a') as f: f.write(json.dumps(row,ensure_ascii=False)+'\n')
        print(event, json.dumps(kw,ensure_ascii=False),flush=True)
    def descendants(self):
        ps=processes(); owned=set(self.owned) | ({self.boot.pid} if self.boot else set())
        while True:
            add={p for p,(pp,_) in ps.items() if pp in owned}
            if add<=owned: break
            owned |= add
        self.owned |= owned
        return owned
    def group_pids(self):
        if not self.boot: return set()
        raw=subprocess.check_output(['ps','-axo','pid=,pgid='],text=True)
        return {int(v[0]) for line in raw.splitlines() if len(v:=line.split())==2 and int(v[1])==self.boot.pid}
    def alive(self):
        if self.pid and self.pid not in processes(): raise RuntimeError('O jogo fechou antes do fim')
    def cmd(self,s):
        self.alive()
        with self.inp.open('a') as f: f.write(s+'\n')
    def key(self,k=38,hold=150):
        self.cmd(f'key {k} {hold}'); time.sleep(2)
    def shot(self):
        self.seq+=1; path=LOGS/f'{self.a.name}_step_{self.seq:03}.png'
        if path.exists(): raise RuntimeError('Foto já existe: use nome de boot novo')
        self.cmd(f'shot {path}')
        end=time.monotonic()+20
        while time.monotonic()<end:
            self.alive()
            if path.exists():
                try:
                    Image.open(path).load(); break
                except (OSError,ValueError): pass
            time.sleep(.3)
        else: raise RuntimeError('Foto não chegou')
        raw=subprocess.check_output(['tesseract',str(path),'stdout','-l','eng','tsv'],text=True,stderr=subprocess.DEVNULL,timeout=20)
        groups={}
        with Image.open(path) as source: width,height=source.size
        for r in csv.DictReader(io.StringIO(raw),delimiter='\t',quoting=csv.QUOTE_NONE):
            if r['level']!='5' or not r['text'].strip(): continue
            groups.setdefault(tuple(r[k] for k in ('block_num','par_num','line_num')),[]).append(r)
        rows=[]
        for words in groups.values():
            x=min(int(r['left']) for r in words); y=min(int(r['top']) for r in words)
            right=max(int(r['left'])+int(r['width']) for r in words); bottom=max(int(r['top'])+int(r['height']) for r in words)
            rows.append(dict(text=' '.join(r['text'] for r in words),box=[x/width,y/height,(right-x)/width,(bottom-y)/height]))
        im=Image.open(path).convert('RGB'); w,h=im.size
        cp=path.with_suffix('.clock.png')
        ImageOps.invert(im.crop((int(w*158/1920),int(h*112/1080),int(w*240/1920),int(h*135/1080)))) .resize((492,138)).save(cp)
        clock_text=subprocess.check_output(['tesseract',str(cp),'stdout','--psm','13','-c','tessedit_char_whitelist=0123456789:'],text=True,stderr=subprocess.DEVNULL,timeout=10).strip()
        if re.fullmatch(r'\d{1,2}:\d{2}',clock_text): rows.insert(0,dict(text=clock_text,box=[.083,.104,.043,.022]))
        path.with_suffix('.ocr.json').write_text(json.dumps(rows,ensure_ascii=False))
        return path,rows
    def start_prompt(self,path,rows):
        """Lê só a legenda estável; o cenário animado não é referência."""
        if re.search(START_PATTERN,norm(' '.join(r['text'] for r in rows))): return rows
        with Image.open(path) as source:
            w,h=source.size
            crop=source.crop((int(.045*w),int(.91*h),int(.28*w),int(.95*h)))
            crop=ImageOps.invert(ImageOps.grayscale(crop)).resize((940,160))
            out=io.BytesIO(); crop.save(out,format='PNG')
        text=subprocess.check_output(['tesseract','stdin','stdout','--psm','7','-l','eng'],
            input=out.getvalue(),stderr=subprocess.DEVNULL,timeout=10).decode().strip()
        if re.search(START_PATTERN,norm(text)):
            self.record('legenda_canto_lida',photo=str(path),text=text)
            return rows+[dict(text=text,box=[.05,.922,.12,.022])]
        return rows
    def confirm(self,path,rows,label,pattern,box=None):
        if not re.search(pattern,norm(' '.join(r['text'] for r in rows))): return False
        if box is None and label=='inicio_botao': box=(.05,.922,.16,.942)
        if box is None and label=='lado': box=(.44,.47,.56,.51)
        if box is None and label=='entrada_em_campo':
            title=next((r for r in rows if norm(r['text']).strip()=='arouca' and .2<r['box'][0]<.5 and .3<r['box'][1]<.7),None)
            if title is None: return False
            x,y,w,h=title['box']; box=(x,y,x+w,y+h)
        if box is None:
            hit=next((r for r in rows if re.search(pattern,norm(r['text']))),None)
            if hit:
                x,y,w,h=hit['box']; box=(x,y,x+w,y+h)
        if box:
            im=Image.open(path).convert('RGB'); w,h=im.size
            crop=im.crop(tuple(int(v*d) for v,d in zip(box,(w,h,w,h)))).resize((400,100))
            ref=self.refs/(f'{label}_titulo.png' if label=='entrada_em_campo' else f'{label}.png')
            if ref.exists():
                diff=sum(ImageStat.Stat(ImageChops.difference(crop,Image.open(ref).convert('RGB'))).mean)/3/255
                self.record('referencia',label=label,difference=diff)
                if diff>.14: return False
            else: crop.save(ref); self.record('referencia_criada_apos_OCR',label=label)
        self.record('tela_confirmada',label=label,photo=str(path)); return True
    def clock(self,rows):
        for r in rows:
            x,y,w,h=r['box']
            if x<.4 and y<.22:
                m=re.fullmatch(r'(\d{1,2})\s*[:;.]\s*(\d{2})',r['text'].strip())
                if m and int(m[2])<60: return int(m[1])*60+int(m[2])
        return None
    def run(self):
        if games():
            if not getattr(self.a,'wait_idle',False): raise RuntimeError('Já existe jogo aberto; nenhuma ação enviada')
            self.record('aguardando_jogo_existente_sem_enviar_comandos')
            # Somente o lançador entra na fila; boot_gpu.sh verifica novamente
            # a ausência de jogo dentro da trava antes de iniciar o binário.
        marker=time.time(); env=os.environ.copy()
        env.update(FC26_BIN=str(Path(self.a.bin).resolve()),FC26_FPS60=str(int(self.a.fps60)),
            DM_PRESENT_HZ='60',FC26_THREAD_PROFILE='1',TOTK_PROFILE_DIR=str(WORK/'user-data-carr-t1'),
            TOTK_SHADER_CACHE=str(WORK/'build-update/shader-cache/rt-update'),FC26_SHADER_WARM='kit',
            DM_NVN_GPUPROF='-1',DM_NVN_GPUPROF_FILE=str(LOGS/f'{self.a.name}.tsv'))
        env.pop('FC26_BOOT_LOCKED',None); env.pop('FC26_PATCHES',None); env.pop('FC26_FORCE_PRESENT_INTERVAL',None)
        with (LOGS/f'{self.a.name}_boot.out').open('w') as f:
            self.boot=subprocess.Popen([str(ROOT/'tools/boot_gpu.sh'),self.a.name,'rewritten/v1638400',str(self.a.warm_timeout+600)],cwd=WORK,env=env,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
        end=time.monotonic()+self.a.slot_timeout
        while time.monotonic()<end:
            descendants=self.descendants()
            if self.log.exists() and self.log.stat().st_mtime>=marker:
                candidates=games() & descendants
                if len(candidates)==1:
                    self.pid=candidates.pop(); self.record('boot_proprio',pid=self.pid); break
            if self.boot.poll() is not None: raise RuntimeError('Lançador terminou antes do boot')
            time.sleep(1)
        else: raise RuntimeError('Tempo da trava esgotado')
        end=time.monotonic()+self.a.warm_timeout
        while time.monotonic()<end:
            self.alive(); text=self.log.read_text(errors='replace')
            if any(int(n)==int(total) and int(total)>0 for n,total in re.findall(r'预热进度：已处理\s*(\d+)\s*/\s*(\d+)',text)):
                self.record('aquecimento_completo'); break
            time.sleep(1)
        else: raise RuntimeError('Aquecimento não terminou no limite')
        # Reconhece cada tela antes de enviar a ação correspondente. Máximo 120 fotos.
        counts={}; clock_prev=None
        for _ in range(120):
            path,rows=self.shot(); rows=self.start_prompt(path,rows); text=norm(' '.join(r['text'] for r in rows)); clock=self.clock(rows)
            if clock is not None:
                if clock_prev and 0<clock-clock_prev[0]<180:
                    elapsed=time.monotonic()-clock_prev[1]
                    self.record('bola_rolando',clock_a=clock_prev[0],clock_b=clock,seconds=elapsed,photo_a=str(clock_prev[2]),photo_b=str(path))
                    return self.measure(clock, path)
                if clock_prev and clock==clock_prev[0]==0:
                    self.record('pontape_inicial_confirmado_pelo_relogio',photo=str(path)); self.key(38)
                clock_prev=(clock,time.monotonic(),path); time.sleep(5); continue
            if re.search(EA_PATTERN,text):
                stage='aviso_ea'
                if not self.confirm(path,rows,stage,r'(ea|servidores|ligacao|conexao)'):
                    self.record('referencia_divergiu_aguardando',label=stage); time.sleep(2); continue
                self.record('aviso_EA_tratado',photo=str(path)); action=38
            elif 'pontape de saida' in text and ('carreira' in text or 'clubes' in text):
                stage='menu_principal'; action=1
                selected=[]
                im=Image.open(path).convert('RGB'); w,h=im.size
                for r in rows:
                    if r['box'][0]<.3 and .15<r['box'][1]<.85:
                        x,y,rw,rh=r['box']; crop=im.crop((int(x*w),int(y*h),int((x+rw)*w),int((y+rh)*h)))
                        vals=sorted(crop.convert('L').get_flattened_data()); bright=vals[int(len(vals)*.9)]
                        selected.append((bright,norm(r['text']),y))
                best=max(selected,default=(0,'',0))
                self.record('selecao_menu',selected=best)
                if 'pontape' in best[1]:
                    if not self.confirm(path,rows,'pontape',r'pontape de saida',(.05,.5,.28,.54)): raise RuntimeError('Referência de Pontapé divergiu')
                    action=38
                else:
                    target=next((r['box'][1] for r in rows if 'pontape de saida' in norm(r['text']) and r['box'][0]<.3),None)
                    action=13 if target is not None and best[2]>target else 1
            else:
                stages=[('inicio_botao',START_PATTERN),('inicio',r'(prime|pression|press).*(iniciar|continuar|start)|jogar offline|vamos jogar'),
                    ('perfil',r'(definicoes pessoais|configuracoes pessoais|carregar perfil)'),
                    ('dificuldade',r'neste primeiro|nivel.*dificuldade|dificuldade.*ajustado'),
                    ('lado',r'(escolher lado|selecionar lado|selecionar lados)'),
                    ('tipo',r'(classica|classico|partida rapida|regras da casa)'),
                    ('equipes',r'(selecionar equip|selecao de equip|selecionar time|selecao de time)'),
                    ('uniformes',r'(equipamento|uniforme).*(visitante|casa|principal)|selecionar equipamento'),
                    ('prepartida',r'comecar encontro|(jogar partida|jogar jogo|iniciar partida|gestao da equipa|definicoes de jogo)'),
                    ('entrada_em_campo',r'arouca.*vs.*rio ave|rio ave.*vs.*arouca'),
                    ('abertura',r'manter para saltar|manter para pular')]
                match=next(((s,p) for s,p in stages if re.search(p,text)),None)
                if match:
                    stage,pattern=match
                    if not self.confirm(path,rows,stage,pattern):
                        self.record('referencia_divergiu_aguardando',label=stage); time.sleep(2); continue
                    action=38
                else:
                    self.record('tela_desconhecida_aguardando',photo=str(path),text=text)
                    counts['unknown']=counts.get('unknown',0)+1
                    if counts['unknown']>60: raise RuntimeError('Tela desconhecida; não envia tecla às cegas')
                    time.sleep(3); continue
            counts[stage]=counts.get(stage,0)+1
            if counts[stage]>16: raise RuntimeError('Limite de tentativas: '+stage)
            self.key(action,2500 if stage in ('abertura','entrada_em_campo') else 150)
            time.sleep(2)
        raise RuntimeError('Navegação excedeu o limite')
    def measure(self,clock,path):
        moving=False
        start=time.monotonic(); self.record('medicao_inicio',clock=clock,photo=str(path))
        self.cmd(f'frameburst 16 {LOGS}/{self.a.name}_burst')
        time.sleep(2)
        if self.a.profile: self.cmd('flag gpuprof 600')
        while time.monotonic()-start<45:
            time.sleep(5); p,rows=self.shot(); current=self.clock(rows); self.record('medicao_foto',photo=str(p),clock=current)
            if current is not None and current>clock: moving=True
        if not moving: raise RuntimeError('O relógio não avançou durante a medição')
        if self.a.profile:
            text=self.log.read_text(errors='replace')
            invalid=re.findall(r'\[gpuprof-invalid\]|dropped [1-9]\d*|invalid [1-9]\d*',text)
            if invalid: raise RuntimeError('Coleta GPU com perda ou marcação inválida')
            tsv=LOGS/f'{self.a.name}.tsv'
            frames={int(v[0]) for l in tsv.read_text().splitlines() if len(v:=l.split('\t'))==13 and v[2] in 'ROBCD'}
            if len(frames)!=600 or max(frames)-min(frames)!=599: raise RuntimeError(f'Coleta incompleta: {len(frames)} quadros')
            self.record('perfil_completo',frames=len(frames))
        self.record('sucesso')
    def close(self):
        self.descendants()
        if self.boot and self.pid is None:
            candidates=games() & self.group_pids()
            if len(candidates)==1:
                self.pid=candidates.pop(); self.record('PID_identificado_na_limpeza',pid=self.pid)
        if self.pid:
            try: self.cmd('close'); self.record('close_enviado',pid=self.pid)
            except (RuntimeError,OSError): pass
            end=time.monotonic()+15
            while self.pid in processes() and time.monotonic()<end: time.sleep(.5)
        if self.boot and self.pid:
            try: self.boot.wait(timeout=4)
            except subprocess.TimeoutExpired: pass
        # Guarda os descendentes antes de interromper o lançador: lockf pode sair antes dos filhos.
        self.descendants()
        self.owned |= self.group_pids()
        ps=processes()
        for pid in sorted(self.owned & self.group_pids(),reverse=True):
            if pid in ps:
                try: os.kill(pid,signal.SIGTERM); self.record('encerramento_PID',pid=pid,command=ps[pid][1])
                except ProcessLookupError: pass
        time.sleep(1)
        for pid in self.group_pids():
            if pid in processes():
                try: os.kill(pid,signal.SIGKILL); self.record('encerramento_forcado_PID',pid=pid)
                except ProcessLookupError: pass
        if self.boot: self.boot.wait(timeout=10)
def main():
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('name'); p.add_argument('--bin',required=True); p.add_argument('--fps60',action='store_true'); p.add_argument('--profile',action='store_true')
    p.add_argument('--wait-idle',action='store_true',help='Aguarda o jogo existente sair, sem enviar comandos'); p.add_argument('--warm-timeout',type=int,default=900); p.add_argument('--slot-timeout',type=int,default=1800)
    a=p.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9_-]+',a.name): p.error('Nome inválido')
    r=Route(a)
    if r.evidence.exists(): p.error('Nome já usado; escolha outro para não misturar provas')
    def interrupted(sig,frame): raise RuntimeError(f'Controlador interrompido pelo sinal {sig}')
    signal.signal(signal.SIGTERM,interrupted); signal.signal(signal.SIGINT,interrupted)
    code=0
    try: r.run()
    except Exception as e: r.record('FALHA',reason=str(e)); code=1
    finally:
        signal.signal(signal.SIGTERM,signal.SIG_IGN); signal.signal(signal.SIGINT,signal.SIG_IGN)
        r.close()
    return code
if __name__=='__main__': sys.exit(main())
