"""Observador com navegação manual após entrar na Carreira.

Usado na prova defeitos_carreira01. O roteiro com estados reconhecidos fica
em rota_carreira.py. Fecha por PARAR_defeitos ou NOME_FECHAR, sempre pela
limpeza da rota robusta. Capturas contínuas mantêm o arquivo de comandos ativo.
"""
from pathlib import Path
import os, time
root=(Path.home() / 'fc26-switch')
p=root/'rev/defeitos/tools/rota_robusta.py'
s=p.read_text().replace("WORK/'user-data-carr-t1'", "WORK/'user-data-defeitos-carr'").replace("WORK/'build-update/shader-cache/rt-update'", "WORK/'build-defeitos/shader-cache/rt-defeitos'")
s=s.replace("if 'pontape' in best[1]:", "if 'treinador' in best[1]:")
s=s.replace("'pontape',r'pontape de saida',(.05,.5,.28,.54)", "'carreira_treinador',r'treinador'")
s=s.replace("'pontape de saida' in norm(r['text'])", "'treinador' in norm(r['text'])")
s=s.replace("            time.sleep(2)\n        raise RuntimeError('Navegação excedeu o limite')", "            time.sleep(2)\n            if stage=='menu_principal' and action==38: return self.manual()\n        raise RuntimeError('Navegação excedeu o limite')")
s=s.replace('str(self.a.warm_timeout+600)', 'str(self.a.warm_timeout+6000)')
ns={'__file__':str(p),'__name__':'rota_carreira_defeitos'}
exec(compile(s,str(p),'exec'),ns)
base_norm=ns['norm']
ns['norm']=lambda text:base_norm(text).replace('saiida','saida').replace('pontape desaida','pontape de saida')
def manual(self):
    self.record('carreira_controle_conferido_pronto')
    until=time.monotonic()+5400
    while time.monotonic()<until:
        if (ns['LOGS']/'PARAR_defeitos').exists() or (ns['LOGS']/(self.a.name+'_FECHAR')).exists():
            self.record('parada_solicitada');return
        path,rows=self.shot()
        self.record('carreira_foto',photo=str(path),clock=self.clock(rows),text=ns['norm'](' '.join(r['text'] for r in rows)))
        time.sleep(5)
    raise RuntimeError('Tempo da sessão da Carreira esgotado')
ns['Route'].manual=manual
if __name__=='__main__':raise SystemExit(ns['main']())
