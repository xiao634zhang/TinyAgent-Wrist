"""Offline setup, privacy and event-output regression checks."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

import configure
import send_notification
import training_monitor
from scripts.check_public_content import findings

ROOT = Path(__file__).resolve().parent


class ConfigurationTests(unittest.TestCase):
    def test_merge_preserves_existing_and_is_idempotent(self):
        old = {'description': 'existing', 'hooks': {'Stop': [{'hooks': [{'command': 'keep-me'}]}]}}
        generated = configure.definitions(Path('C:/install path'), Path('C:/python/python.exe'))
        configure.merge_hooks(old, generated); configure.merge_hooks(old, generated)
        self.assertEqual(len(old['hooks']['Stop']), 2)
        self.assertEqual(old['hooks']['Stop'][0]['hooks'][0]['command'], 'keep-me')
        self.assertIn('"' + str(Path('C:/install path') / 'codex_notify_hook.py') + '"', old['hooks']['Stop'][1]['hooks'][0]['command'])

    def test_setup_uses_temp_codex_home_and_preserves_topic(self):
        with tempfile.TemporaryDirectory(prefix='wrist setup ') as temp:
            root = Path(temp); home = root / 'test-home'; home.mkdir()
            (home/'hooks.json').write_text('{"hooks":{"Stop":[{"hooks":[{"command":"preserved"}]}]}}', encoding='utf-8')
            (home/'AGENTS.md').write_text('Existing instructions.\n', encoding='utf-8')
            for name in ('configure.py', 'notification_config.example.json', 'training_monitor_config.example.json'):
                shutil.copy2(ROOT/name, root/name)
            command = [sys.executable, str(root/'configure.py'), '--codex-home', str(home), '--install-hooks', '--install-rules']
            subprocess.run(command, check=True, capture_output=True)
            config = json.loads((root/'notification_config.json').read_text(encoding='utf-8'))
            subprocess.run(command, check=True, capture_output=True)
            self.assertEqual(json.loads((root/'notification_config.json').read_text())['topic'], config['topic'])
            self.assertEqual(len(config['topic']), 38)
            self.assertFalse(config['permission_notifications'])
            self.assertEqual(len(json.loads((home/'hooks.json').read_text())['hooks']['Stop']), 2)
            rules = (home/'AGENTS.md').read_text(encoding='utf-8')
            self.assertTrue(rules.startswith('Existing instructions.'))
            self.assertEqual(rules.count('<!-- codex-wrist-notify:start -->'), 1)

    def test_topic_must_be_configured(self):
        with self.assertRaises(ValueError): send_notification.send('https://ntfy.sh', '', 'do not send')

    def test_token_never_falls_back_to_curl(self):
        with patch.dict('os.environ', {'NTFY_TOKEN': 'synthetic-test-value'}):
            with patch('send_notification.urllib.request.urlopen', side_effect=URLError('offline')) as request:
                with patch('send_notification.via_ipv6') as fallback:
                    with self.assertRaises(URLError): send_notification.send('https://ntfy.sh', 'offline-test', 'test')
                    self.assertEqual(request.call_args.args[0].get_header('Authorization'), 'Bearer synthetic-test-value')
                    fallback.assert_not_called()

    def test_scanner_reports_only_rule_names(self):
        fake = ('ghp_' + 'a'*36).encode()
        self.assertIn('github-token', findings('sample.txt', fake))
        self.assertIn('private-runtime-file', findings('logs/sample.txt', b'local'))
        self.assertEqual(findings('notification_config.example.json', b'{"topic":"REPLACE_WITH_YOUR_RANDOM_TOPIC"}'), [])

    def test_training_notification_stdout_is_one_json_document_and_deduped(self):
        data = {'run_id': 'synthetic-complete', 'status': 'TRAINING_COMPLETE', 'stages': {}}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'training_monitor_config.json').write_text(json.dumps({'server': 'https://ntfy.sh', 'topic': 'offline-test', 'targets': [{'name': 'Example', 'url': 'http://127.0.0.1:9876'}]}))
            result = {'target': {'name': 'Example', 'url': 'http://127.0.0.1:9876'}, 'data': data, 'curves': {}, 'warnings': []}
            with patch.object(training_monitor, 'ROOT', root), patch.object(training_monitor, 'collect', return_value=result):
                with patch.object(sys, 'argv', ['monitor', '--notify']):
                    with patch('send_notification.send', side_effect=lambda *a, **k: print('{"id":"synthetic-receipt"}')) as sender:
                        output = io.StringIO()
                        with contextlib.redirect_stdout(output): training_monitor.main()
                        summary = json.loads(output.getvalue())
                        self.assertTrue(summary['alerts'][0]['sent'])
                        output = io.StringIO()
                        with contextlib.redirect_stdout(output): training_monitor.main()
                        self.assertEqual(json.loads(output.getvalue())['alerts'], [])
                        self.assertEqual(sender.call_count, 1)


if __name__ == '__main__': unittest.main()
