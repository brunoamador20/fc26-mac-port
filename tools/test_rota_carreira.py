"""Conferências da navegação real, sem abrir o jogo."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image

spec=importlib.util.spec_from_file_location('carreira',Path(__file__).with_name('rota_carreira.py'))
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)

class CareerRouteTests(unittest.TestCase):
    def test_date_is_exact_and_valid(self):
        self.assertEqual(c.career_date('Data atual: 12/8/2025'),'12/8/2025')
        self.assertNotEqual(c.career_date('Data atual: 16/8/2025'),'6/8/2025')
        self.assertIsNone(c.career_date('Data atual: 31/2/2025'))
        self.assertIsNone(c.career_date('Última modificação: 12/8/2025'))

    def test_postgame_date_uses_title_before_next_fixture(self):
        self.assertEqual(c.central_date('terça, 12 de ago próxima jornada 15 de agosto'),'12/8/2025')
        self.assertIsNone(c.central_date('12 de agosto'))

    def test_unknown_menu_waits_without_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'frame.png';Image.new('RGB',(192,108)).save(path)
            events=[];keys=[]
            route=SimpleNamespace(record=lambda *a,**k:events.append(a[0]),key=keys.append)
            with patch.object(c.time,'sleep'):
                c.Route.menu(route,path,[{'text':'PONTAPÉ DE SAÍDA','box':[.05,.56,.2,.02]}])
            self.assertEqual(keys,[])
            self.assertEqual(events,['menu_animado_aguardando'])

    def test_stop_does_not_prevent_cleanup(self):
        route=object.__new__(c.Route)
        with patch.object(c.Base,'alive'),patch.object(c.Path,'exists',return_value=True):
            with self.assertRaisesRegex(RuntimeError,'Parada'):
                route.alive()
            with patch.object(c.Base,'close',side_effect=lambda:c.Route.alive(route)):
                route.close()
            self.assertTrue(route.cleaning)

    def test_real_button_focus(self):
        paths=[c.LOGS/f'defeitos_carreira01_step_{n}.png' for n in ('035','046','292','299')]
        if not all(p.exists() for p in paths):self.skipTest('Capturas locais ausentes')
        self.assertEqual([c.selected_advance(p) for p in paths],[False,True,False,True])

    def test_real_selected_save_button(self):
        path=c.LOGS/'defeitos_carreira01_step_315.png'
        if not path.exists():self.skipTest('Captura local ausente')
        self.assertRegex(c.region_text(path,(.41,.65,.60,.685)),r'guardar.*automaticamente.*sair')

if __name__=='__main__':unittest.main()
