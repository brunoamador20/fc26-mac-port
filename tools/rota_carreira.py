#!/usr/bin/env python3
"""Carreira no perfil separado: navegação conferida, jogo e reabertura.

Usa a trava, aquecimento, fotos, parada e limpeza da rota robusta.
Sem --verify, observa a partida inteira; --verify DATA confere a Carreira
reaberta. Fontes e imagens do jogo nunca entram no repositório.
"""
import argparse
import datetime
import json
import io
import re
import signal
import subprocess
import time
from pathlib import Path
from PIL import Image

SOURCE = Path(__file__).with_name('rota_robusta.py')
source = SOURCE.read_text()
source = source.replace("WORK/'user-data-carr-t1'", "WORK/'user-data-defeitos-carr'")
source = source.replace("WORK/'build-update/shader-cache/rt-update'", "WORK/'build-defeitos/shader-cache/rt-defeitos'")
source = source.replace('str(self.a.warm_timeout+600)', 'str(self.a.warm_timeout+6000)')
anchor = '        # Reconhece cada tela antes de enviar a ação correspondente.'
assert source.count(anchor) == 1
source = source.replace(anchor, '        return self.navigate()\n' + anchor)
ns = {'__file__': str(SOURCE), '__name__': 'robusto_carreira'}
exec(compile(source, str(SOURCE), 'exec'), ns)
Base = ns['Route']
WORK, LOGS = ns['WORK'], ns['LOGS']
norm = ns['norm']


def career_date(text):
    match = re.search(r'data atual:\s*(\d{1,2})/(\d{1,2})/(\d{4})', norm(text))
    if not match:
        return None
    try:
        day, month, year = map(int, match.groups())
        date = datetime.date(year, month, day)
    except ValueError:
        return None
    return f'{date.day}/{date.month}/{date.year}'


def region_text(path, box):
    with Image.open(path).convert('RGB') as im:
        w,h=im.size
        crop=im.crop(tuple(int(v*d) for v,d in zip(box,(w,h,w,h))))
        crop=crop.resize((1000,150))
        data=io.BytesIO();crop.save(data,format='PNG')
    return norm(subprocess.check_output(['tesseract','stdin','stdout','--psm','7'],input=data.getvalue(),stderr=subprocess.DEVNULL,timeout=15).decode())


def central_date(text):
    match=re.search(r'\b(\d{1,2}) de ago\b',norm(text))
    return f'{int(match[1])}/8/2025' if match and 1<=int(match[1])<=31 else None


def white_text(path,box):
    with Image.open(path).convert('RGB') as im:
        w,h=im.size
        pixels=list(im.crop(tuple(int(v*d) for v,d in zip(box,(w,h,w,h)))).get_flattened_data())
    return sum(min(pixel)>220 for pixel in pixels)/len(pixels)>.015


def selected_advance(path):
    """A borda azul distingue o botão de avanço das tarefas logo abaixo."""
    with Image.open(path).convert('RGB') as im:
        w, h = im.size
        pixels = list(im.crop((int(.11*w), int(.51*h), int(.24*w), int(.59*h))).get_flattened_data())
    return sum(g > 130 and b > 130 and r < 100 for r, g, b in pixels) / len(pixels) > .035


class Route(Base):
    def alive(self):
        super().alive()
        if not getattr(self,'cleaning',False) and ((LOGS/'PARAR_defeitos').exists() or (LOGS/'PARAR_carreira').exists()):
            raise RuntimeError('Parada solicitada')

    def close(self):
        self.cleaning=True
        return super().close()

    def memory(self, label):
        path = LOGS/f'{self.a.name}_mem_{label}.txt'
        result = subprocess.run(['vmmap', '-summary', str(self.pid)], capture_output=True, text=True, timeout=30)
        path.write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError('Medição de memória falhou')
        match = re.search(r'Physical footprint:\s*([^\n]+)', result.stdout)
        self.record('memoria', label=label, value=match.group(1).strip() if match else None, file=str(path))

    def menu(self, path, rows):
        with Image.open(path).convert('RGB') as im:
            w,h=im.size
            items=[]
            for r in rows:
                x,y,rw,rh=r['box']
                if x<.3 and x+rw<.29 and .15<y<.85:
                    values=sorted(im.crop((int(x*w),int(y*h),int((x+rw)*w),int((y+rh)*h))).convert('L').get_flattened_data())
                    if values: items.append((values[int(len(values)*.9)], norm(r['text']), y))
        best=max(items, default=(0,'',0))
        if 'treinador' in best[1]:
            self.record('carreira_menu_confirmado', photo=str(path))
            self.key(38)
            return
        target=next((r['box'][1] for r in rows if 'treinador' in norm(r['text']) and r['box'][0]<.3), None)
        if target is None:
            self.record('menu_animado_aguardando',photo=str(path))
            time.sleep(3)
            return
        self.key(13 if best[2]>target else 1)

    def inspect_save(self):
        end=time.monotonic()+900
        while time.monotonic()<end:
            if (LOGS/(self.a.name+'_FECHAR')).exists(): return
            path,rows=self.shot()
            self.record('save_consulta',photo=str(path),text=norm(' '.join(r['text'] for r in rows)))
            time.sleep(5)
        raise RuntimeError('Limite da consulta ao save')

    def navigate(self):
        end=time.monotonic()+5400
        playing=False
        last_clock=None
        start=None
        interval=False
        finished=False
        post_date=None
        advanced=False
        saving=False
        result=None
        stopped_clock=0
        for index in range(900):
            if time.monotonic()>end: raise RuntimeError('Tempo da Carreira esgotado')
            path,rows=self.shot()
            rows=self.start_prompt(path,rows)
            text=norm(' '.join(r['text'] for r in rows))
            clock=self.clock(rows)
            self.record('carreira_foto',photo=str(path),clock=clock,text=text)
            if saving and 'pontape de saida' in text and 'treinador' in text:
                self.record('carreira_guardada',photo=str(path),date=post_date)
                (LOGS/f'{self.a.name}_save.json').write_text(json.dumps({'date':post_date,'result':result},indent=2))
                return
            if clock is not None:
                if not playing and clock>0:
                    playing=True; start=time.time()
                    self.record('partida_inicio',photo=str(path),clock=clock)
                    self.memory('inicio')
                if clock==last_clock==0: self.key(38)
                stopped_clock = stopped_clock+1 if clock==last_clock else 0
                if stopped_clock>=3 and re.search(r'passe\s*rasteiro',text) and 'pedir aproxim' in text:
                    self.record('reposicao_goleiro',photo=str(path)); self.key(40); stopped_clock=0
                last_clock=clock
                time.sleep(5)
                continue
            if 'jogar offline' in text or re.search(ns['EA_PATTERN'],text) or 'passe de epoca esta atualmente indisponivel' in text:
                self.key(38)
            elif re.search(ns['START_PATTERN'],text) or 'vamos jogar' in text:
                self.key(38)
            elif 'data atual:' in text and 'criar nova' in text:
                if self.a.verify:
                    if career_date(text) != self.a.verify: raise RuntimeError('Data gravada divergente')
                    self.record('save_reaberto_confirmado',photo=str(path),date=self.a.verify)
                self.key(38)
            elif 'ao vivo' in text and 'original' in text:
                self.key(1); self.key(38)
            elif 'pontape de saida' in text and 'treinador' in text:
                self.menu(path,rows)
            elif 'central' in text and 'notific' in text and ('jornada' in text or 'avs futebol' in text):
                if self.a.verify:
                    self.record('carreira_recarregada',photo=str(path),text=text)
                    if self.a.inspect:
                        return self.inspect_save()
                    return
                if playing:
                    if not finished or result is None: raise RuntimeError('Carreira voltou sem prova do fim e placar')
                    date=central_date(text)
                    if date is None:
                        time.sleep(3); continue
                    if post_date is None:
                        post_date=date
                        self.record('partida_retornou_carreira',photo=str(path),date=date,seconds=time.time()-start)
                    elif date!=post_date:
                        advanced=True;post_date=date
                        self.record('carreira_avancou_apos_jogo',photo=str(path),date=date)
                    if advanced:
                        self.key(40)
                    elif selected_advance(path):
                        self.key(38)
                    else:
                        self.key(13)
                    continue
                if selected_advance(path): self.key(38)
                else: self.key(13)
            elif 'jogar encontro' in text and 'vista tatica' in text:
                self.key(38)
            elif playing and re.search(r'fim do jogo|fim de jogo|fim da partida|final do jogo',text):
                if not finished:
                    finished=True
                    self.record('apito_final',photo=str(path),seconds=time.time()-start,text=text)
                    self.memory('apito')
                time.sleep(3)
            elif finished and '90:00' in text and 'carreira' in text:
                score=re.search(r'\b(\d+)\s*-\s*(\d+)\b',text)
                if score: result=f'{score[1]}-{score[2]}'
                if result is None:
                    self.record('placar_final_aguardando',photo=str(path));time.sleep(3)
                elif white_text(path,(.05,.25,.15,.28)):
                    self.record('menu_final_avancar',photo=str(path),result=result);self.key(38)
                elif white_text(path,(.05,.19,.26,.22)):
                    self.record('menu_final_entrevista_selecionada',photo=str(path));self.key(1)
                else:
                    self.record('menu_final_aguardando',photo=str(path));time.sleep(3)
            elif finished and ('utiliza o menu alternar' in text or 'podes adicionar a lista' in text):
                self.key(38)
            elif advanced and 'sair do modo carreira' in text:
                selected=region_text(path,(.41,.65,.60,.685))
                if not re.search(r'guardar.*automaticamente.*sair',selected):
                    raise RuntimeError('Botão de guardar automaticamente não confirmado')
                self.record('guardar_confirmado',photo=str(path),text=selected)
                saving=True;self.key(38)
            elif playing and 'continuar' in text and re.search(r'troca de taticas|configuragao tatica|sugest.es taticas',text):
                self.record('tutorial_taticas',photo=str(path)); self.key(38)
            elif playing and 'intervalo' in text:
                interval=True
                self.record('intervalo',photo=str(path)); self.memory('intervalo')
                time.sleep(3)
            elif playing and (('45:00' in text and 'voltar ao jogo' in text) or (interval and 'avancar' in text)):
                self.record('intervalo_avancar',photo=str(path)); self.key(38)
            else:
                self.record('aguardando_tela_sem_teclas',photo=str(path))
                time.sleep(3)
        raise RuntimeError('Limite de fotos da Carreira')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name')
    parser.add_argument('--verify', metavar='DATA')
    parser.add_argument('--inspect',action='store_true',help='Mantém fotos após recarregar para conferir o resultado')
    parser.add_argument('--bin',default=str(WORK/'build-defeitos/fc26-native'))
    args=parser.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9_-]+',args.name): parser.error('Nome inválido')
    args.fps60=False; args.profile=False; args.wait_idle=True; args.warm_timeout=900; args.slot_timeout=1800
    route=Route(args)
    if route.evidence.exists(): parser.error('Nome já usado')
    def stop(sig,frame): raise RuntimeError('Controlador interrompido')
    signal.signal(signal.SIGTERM,stop); signal.signal(signal.SIGINT,stop)
    result=0
    try: route.run()
    except Exception as exc:
        route.record('FALHA',reason=str(exc));result=1
    finally:
        signal.signal(signal.SIGTERM,signal.SIG_IGN);signal.signal(signal.SIGINT,signal.SIG_IGN)
        route.close()
    return result

if __name__=='__main__': raise SystemExit(main())
