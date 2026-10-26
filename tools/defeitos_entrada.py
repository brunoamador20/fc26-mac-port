"""Observa a seleção de uniformes e a apresentação inteira usando a rota robusta."""
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
p = Path(__file__).with_name('rota_robusta.py')
source = p.read_text().replace("WORK/'user-data-carr-t1'", "WORK/'user-data-defeitos-carr'")
source = source.replace("WORK/'build-update/shader-cache/rt-update'", "WORK/'build-defeitos/shader-cache/rt-defeitos'")
source = source.replace("counts['unknown']>60", "counts['unknown']>180")
source = source.replace('time.sleep(3); continue', 'time.sleep(.5); continue')
ns = {'__file__': str(p), '__name__': 'rota_entrada_defeitos'}
exec(compile(source, str(p), 'exec'), ns)
r = SimpleNamespace(**ns)
base_norm = r.norm
def norm(text):
    return base_norm(text).replace('saiida', 'saida').replace('pontape desaida', 'pontape de saida')
ns['norm'] = r.norm = norm
base_alive = r.Route.alive
def alive(self):
    base_alive(self)
    if not getattr(self,'cleaning',False) and (r.LOGS/'PARAR_defeitos').exists():
        raise RuntimeError('Parada solicitada')
r.Route.alive = alive
base_close = r.Route.close
def close(self):
    self.cleaning=True
    return base_close(self)
r.Route.close = close
base_measure = r.Route.measure
def measure(self, clock, path):
    base_measure(self, clock, path)
    self.cmd('passdump 2')
    r.time.sleep(2)
    self.cmd(f'texdump {r.LOGS}/{self.a.name}_tex%d.png')
    r.time.sleep(8)
    p, rows = self.shot()
    self.record('comandos_e_texturas_capturados', photo=str(p))
r.Route.measure = measure
original=r.Route.confirm
def confirm(self,path,rows,label,pattern,box=None):
    ok=original(self,path,rows,label,pattern,box)
    if not ok:return False
    if label=='lado' and not getattr(self,'uniformes_observados',False):
        self.uniformes_observados=True
        # A tela confirmada contém Começar encontro e Selecionar equipamentos.
        self.key(1);self.key(1)
        p,rr=self.shot();self.record('uniformes_opcao',photo=str(p),text=' '.join(x['text'] for x in rr))
        # O OCR inteiro perde o botão sobre os jogadores: ler apenas o botão.
        crop=p.with_suffix('.equipamentos.png')
        im=Image.open(p);w,h=im.size
        im.crop((int(.43*w),int(.39*h),int(.59*w),int(.44*h))).resize((960,150)).save(crop)
        text=subprocess.check_output(['tesseract',str(crop),'stdout','--psm','7'],stderr=subprocess.DEVNULL,text=True)
        self.record('uniformes_botao_lido',text=text)
        if 'equipamento' not in r.norm(text):raise RuntimeError('Seleção de equipamentos não apareceu')
        self.key(38);r.time.sleep(3)
        p,rr=self.shot();self.record('uniformes_selecao',photo=str(p),text=' '.join(x['text'] for x in rr))
        if os.environ.get('FC26_KITS_TODOS')=='1':
            self.key(2)
            p,rr=self.shot();self.record('uniformes_casa_alternativo',photo=str(p),text=' '.join(x['text'] for x in rr))
            self.key(0);self.key(38)
            self.key(2)
            p,rr=self.shot();self.record('uniformes_fora_principal',photo=str(p),text=' '.join(x['text'] for x in rr))
            self.key(0);self.key(38)
        else:
            self.key(38);self.key(38)
        return False
    if label in ('entrada_em_campo','abertura') and not getattr(self,'entrada_observada',False):
        self.entrada_observada=True
        if os.environ.get('FC26_RODA_SALTAR')=='1':
            self.key(38,2500)
        last_pulse=r.time.monotonic()
        for i in range(220):
            if not getattr(self,'cleaning',False) and (r.LOGS/'PARAR_defeitos').exists():raise RuntimeError('Parada solicitada na apresentação')
            if os.environ.get('FC26_RODA_PULSOS')=='1' and r.time.monotonic()-last_pulse>20:
                self.record('pulso_curto_apresentacao',hold=150)
                self.key(38);self.key(38);last_pulse=r.time.monotonic()
            p,rr=self.shot();self.record('apresentacao_completa_foto',photo=str(p),clock=self.clock(rr))
            if self.clock(rr) is not None:break
            r.time.sleep(.5)
        return False
    return ok
r.Route.confirm=confirm
if __name__=='__main__':raise SystemExit(r.main())
