"""Verificações de segurança; não abre jogo nem envia sinais reais."""
import argparse
import importlib.util
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import Mock, patch
spec = importlib.util.spec_from_file_location('rota', Path(__file__).with_name('rota_robusta.py'))
rota = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rota)

class Safety(unittest.TestCase):
    def route(self):
        r = rota.Route(argparse.Namespace(name='test_safety'))
        r.record = Mock()
        return r

    def test_refuses_existing_game_before_launch(self):
        r = self.route()
        with patch.object(rota, 'games', return_value={91}), patch.object(rota.subprocess, 'Popen') as launch:
            with self.assertRaisesRegex(RuntimeError, 'Já existe jogo'):
                r.run()
            launch.assert_not_called()
        self.assertIsNone(r.pid)

    def test_follows_lockf_and_game_but_excludes_player(self):
        r = self.route(); r.boot = Mock(pid=10)
        ps = {10:(1,'lockf'),11:(10,'shell'),12:(11,'game'),90:(1,'player')}
        with patch.object(rota,'processes',return_value=ps):
            self.assertEqual(r.descendants(),{10,11,12})
        self.assertNotIn(90,r.owned)

    def test_follows_children_after_launcher_exits(self):
        r = self.route(); r.boot = Mock(pid=10); r.owned={10,11}
        with patch.object(rota,'processes',return_value={11:(1,'watcher'),12:(11,'tail'),90:(1,'player')}):
            self.assertIn(12,r.descendants())
            self.assertNotIn(90,r.owned)

    def test_cleanup_without_own_boot_sends_no_commands_or_signals(self):
        r = self.route(); r.cmd=Mock()
        with patch.object(rota,'processes',return_value={90:(1,'player')}), patch.object(rota.os,'kill') as kill, patch.object(rota.time,'sleep'):
            r.close()
            kill.assert_not_called(); r.cmd.assert_not_called()

    def test_quote_in_ocr_does_not_swallow_next_lines(self):
        r = self.route()
        raw = ('level\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\ttext\n'
               '5\t1\t1\t1\t10\t20\t30\t20\t"\n'
               '5\t2\t1\t1\t10\t50\t90\t20\tPONTAPE\n')
        with tempfile.TemporaryDirectory() as d, patch.object(rota,'LOGS',Path(d)):
            def make_photo(command):
                rota.Image.new('RGB',(1920,1080),'black').save(command.split(' ',1)[1])
            r.cmd=make_photo
            with patch.object(rota.subprocess,'check_output',side_effect=[raw,'05:08']):
                _, rows=r.shot()
            self.assertTrue(any(row['text']=='PONTAPE' for row in rows))
            self.assertEqual(r.clock(rows),308)

    def test_cleanup_uses_own_process_group_even_after_reparenting(self):
        r=self.route(); r.boot=Mock(pid=10); r.owned={91}
        with patch.object(rota,'processes',return_value={12:(1,'own orphan'),91:(1,'player')}), patch.object(rota.subprocess,'check_output',return_value='12 10\n91 91\n'), patch.object(rota.os,'kill') as kill, patch.object(rota.time,'sleep'):
            r.close()
        self.assertTrue(kill.called)
        self.assertTrue(all(c.args[0]==12 for c in kill.call_args_list))

    def test_reconnect_hint_and_team_do_not_become_ea_dialog(self):
        self.assertIsNone(re.search(rota.EA_PATTERN,'prime para reconectar ultimate team pontape de saida'))
        self.assertIsNotNone(re.search(rota.EA_PATTERN,'deves ter sessao iniciada nos servidores ea de modo a aceder'))

    def test_intro_reference_follows_the_title_not_the_animation_background(self):
        r=self.route()
        with tempfile.TemporaryDirectory() as d:
            r.refs=Path(d)
            for shift in (0,13):
                image=rota.Image.new('RGB',(1000,1000),'white')
                image.paste((0,0,0),(280,450+shift,380,470+shift))
                photo=Path(d)/f'frame{shift}.png'; image.save(photo)
                rows=[dict(text='AROUCA',box=[.28,(450+shift)/1000,.1,.02]),
                      dict(text='vs RIO AVE FC',box=[.28,.65,.1,.02])]
                self.assertTrue(r.confirm(photo,rows,'entrada_em_campo',r'arouca.*vs.*rio ave'))

    def test_invalid_clock_seconds_are_rejected(self):
        r=self.route()
        self.assertIsNone(r.clock([dict(text='05:99',box=[.08,.10,.04,.02])]))

if __name__ == '__main__': unittest.main()
