#!/usr/bin/env python3
"""Experimento de IA usando exclusivamente a navegação da rota robusta."""
import argparse
import re
import signal
import statistics
import subprocess
import time
from pathlib import Path
import rota_robusta as robust

FIELDS = {
    'percepcao': ('EnableHighPrequencyPerceptionUpdate', '1'),
    'passes': ('EnableExtraPassEvaluations', '1'),
    'reducao': ('EnablePPCriticalReducedEvaluation', '0'),
    'alternancia': ('EnablePPAlternateFrameOptimization', '0'),
    'combinado': (('EnableHighPrequencyPerceptionUpdate', '1'), ('EnableExtraPassEvaluations', '1'), ('EnablePPCriticalReducedEvaluation', '0')),
}

class Route(robust.Route):
    def alive(self):
        super().alive()
        if (robust.LOGS / 'PARAR_recursos').exists():
            raise RuntimeError('Arquivo PARAR_recursos presente')

    def record(self, event, **kw):
        super().record(event, **kw)
        if event == 'tela_confirmada' and kw.get('label') == 'pontape' and not getattr(self, 'written', False):
            pairs = FIELDS[self.a.adjustment]
            for field, value in (pairs if pairs else ()):
                self.cmd(f'gameplay set {field} {value}')
                self.written = True
                super().record('escrita_solicitada_no_menu', field=field, value=value)

    def measure(self, clock, path):
        if not getattr(self, 'written', False):
            raise RuntimeError('Não houve escrita no menu confirmado')
        self.cmd('gameplay')
        self.cmd(f'frameburst 16 {robust.LOGS}/{self.a.name}_burst')
        self.record('medicao_inicio', clock=clock, photo=str(path))
        start = time.monotonic()
        with (robust.LOGS / f'{self.a.name}_top.txt').open('w') as out:
            top = subprocess.Popen(['top', '-l', '21', '-s', '1', '-pid', str(self.pid), '-stats', 'pid,command,cpu,power'], stdout=out, stderr=subprocess.STDOUT)
        cpus = []
        sample = subprocess.Popen(['sample', str(self.pid), '20', '1', '-file', str(robust.LOGS / f'{self.a.name}_sample.txt')], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.owned.update((top.pid, sample.pid))
        previous = clock
        advance = 0
        perception = 0
        frame_pattern = re.compile(r'计时至帧.*?/\s*([\d.]+)')
        top_done = False
        sample_done = False
        while time.monotonic() - start < 125:
            self.alive()
            time.sleep(5)
            if not top_done:
                top.poll()
                if top.poll() is not None: top_done = True
            if not sample_done:
                sample.poll()
                if sample.poll() is not None: sample_done = True
            photo, rows = self.shot()
            current = self.clock(rows)
            self.record('medicao_foto', photo=str(photo), clock=current)
            if top.poll() is not None:
                text = (robust.LOGS / f'{self.a.name}_top.txt').read_text(errors='replace')
                match = re.findall(rf'^{self.pid}\s+fc26-native\s+([0-9.]+)', text, re.M)
                if match: cpus = [float(v) for v in match]
            perception += len(frame_pattern.findall(self.log.read_text(errors='replace')))
            if current is not None:
                if 0 < current - previous < 180:
                    advance += current - previous
                previous = current
        top.wait(timeout=5)
        sample.wait(timeout=5)
        log_text = self.log.read_text(errors='replace')
        frames = [float(v) for v in re.findall(r'帧时间 p50 ([\d.]+)', log_text)]
        p95_values = [float(v) for v in re.findall(r'帧时间 p50 [\d.]+ / p95 ([\d.]+)', log_text)]
        p50 = statistics.median(frames) if frames else None
        p95 = statistics.median(p95_values) if p95_values else None
        self.record('medida_final', cpu_media=sum(cpus)/len(cpus) if cpus else None,
                    cpu_amostras=len(cpus), quadro_p50=p50, quadro_p95=p95,
                    quadro_amostras=len(frames), chamadas_percepcao_lidas=perception)
        if advance < 600:
            raise RuntimeError('Avanço insuficiente do relógio em dois minutos')
        self.cmd('gameplay')
        time.sleep(2)
        text = self.log.read_text(errors='replace')
        # A leitura inteira fica preservada para conferência; não se confunde
        # escrita solicitada com valor confirmado nem amostragem com prova.
        if 'REFUSED' in text:
            raise RuntimeError('Diagnóstico recusou uma operação')
        self.record('estabilidade_concluida', seconds=time.monotonic()-start, clock_advance=advance, adjustment=self.a.adjustment)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name')
    parser.add_argument('adjustment', choices=FIELDS)
    args = parser.parse_args()
    args.bin = str(robust.WORK / 'build-recursos/fc26-native')
    args.fps60 = False
    args.profile = False
    args.wait_idle = True
    args.slot_timeout = 1800
    args.warm_timeout = 900
    route = Route(args)
    if route.evidence.exists():
        parser.error('Nome já usado')
    if (robust.LOGS / 'PARAR_recursos').exists():
        parser.error('Arquivo de parada presente')
    def interrupted(sig, frame):
        raise RuntimeError(f'Sinal {sig}')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    result = 0
    try:
        route.run()
    except Exception as exc:
        route.record('FALHA', reason=str(exc))
        result = 1
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        # A limpeza precisa continuar mesmo com o arquivo de parada presente.
        route.alive = lambda: robust.Route.alive(route)
        route.close()
    return result

if __name__ == '__main__':
    raise SystemExit(main())
