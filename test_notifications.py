"""Offline content, question format, deduplication and passive behavior tests."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import io
import contextlib
from urllib.error import URLError, HTTPError
import send_notification
from codex_notify_hook import DEFAULTS, clean, deliver, format_event, suppression_reason


class NotificationTests(unittest.TestCase):
    def test_background_suggestion_filter(self):
        config = dict(DEFAULTS, only_user_thread_completions=True)
        self.assertIsNone(suppression_reason('Stop', {}, config, {'known': True, 'thread_source': 'user', 'source': 'vscode'}))
        self.assertEqual(suppression_reason('Stop', {}, config, {'known': True, 'thread_source': 'user', 'source': 'composer_prediction'}), 'background-suggestion')
        self.assertEqual(suppression_reason('Stop', {}, config, {'known': False}), 'not-a-user-thread-completion')
        self.assertIsNone(suppression_reason('PreToolUse', {}, config, {'known': False}))
        self.assertEqual(suppression_reason('Stop', {'last_assistant_message': '{"suggestion":"下一步验证"}'}, config,
                                           {'known': True, 'thread_source': 'user'}), 'composer-suggestion-payload')
        self.assertIsNone(suppression_reason('Stop', {'last_assistant_message': '任务完成，建议稍后备份。'}, config,
                                            {'known': True, 'thread_source': 'user'}))

    def test_network_failure_uses_same_service_ipv6(self):
        with patch('send_notification.urllib.request.urlopen', side_effect=URLError('timeout')):
            with patch('send_notification.via_ipv6', return_value={'id': 'ok', 'event': 'message'}) as fallback:
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    send_notification.send('https://ntfy.sh', 'test-topic', '具体完成结果', 'Codex 完成')
                self.assertEqual(fallback.call_args.args[0], 'https://ntfy.sh')
                self.assertEqual(json.loads(fallback.call_args.args[1])['message'], '具体完成结果')
                self.assertEqual(json.loads(out.getvalue())['transport'], 'ipv6-fallback')

    def test_http_rejection_is_not_republished(self):
        error = HTTPError('https://ntfy.sh', 429, 'rate limited', {}, None)
        with patch('send_notification.urllib.request.urlopen', side_effect=error):
            with patch('send_notification.via_ipv6') as fallback:
                with self.assertRaises(HTTPError):
                    send_notification.send('https://ntfy.sh', 'test-topic', 'test')
                fallback.assert_not_called()

    def test_ipv6_keeps_tls_hostname_and_body_on_stdin(self):
        with patch('send_notification.ipv6_address', return_value='2001:db8::1'):
            with patch('send_notification.shutil.which', return_value='curl.exe'):
                with patch('send_notification.urllib.request.getproxies', return_value={'https': 'http://127.0.0.1:8080'}):
                    with patch('send_notification.subprocess.run') as run:
                        run.return_value.returncode = 0
                        run.return_value.stdout = b'{"id":"ok"}'
                        send_notification.via_ipv6('https://ntfy.sh', b'private-body')
                        command = run.call_args.args[0]
                        self.assertIn('ntfy.sh:443:[2001:db8::1]:443', command)
                        self.assertEqual(command[-1], 'https://ntfy.sh')
                        self.assertNotIn('-k', command)
                        self.assertEqual(run.call_args.kwargs['input'], b'private-body')

    def test_suggestions_not_published_but_normal_results_are(self):
        config = dict(DEFAULTS, only_user_thread_completions=True)
        sent = []
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            payload = {'session_id': 'session-test', 'last_assistant_message': '下一步验证通知'}
            sender = lambda *args: sent.append(args)
            self.assertEqual(deliver('Stop', payload, config, root, sender, lambda p: {'known': False}), 'suppressed')
            self.assertEqual(sent, [])
            with patch.dict('os.environ', {'CODEX_INTERNAL_ORIGINATOR_OVERRIDE': 'codex_vscode'}):
                self.assertEqual(deliver('Stop', payload, config, root, sender,
                                        lambda p: {'known': True, 'thread_source': 'user', 'originator': 'codex_vscode'}), 'sent')
            self.assertEqual(len(sent), 1)
            self.assertIn('VSCode', sent[0][3])
    def test_completion_content(self):
        title, body = format_event('Stop', {'last_assistant_message': '**修复完成**。\n测试 8 项通过。'})
        self.assertEqual(title, 'Codex 完成')
        self.assertIn('修复完成', body)
        self.assertIn('测试 8 项通过', body)

    def test_approval_content(self):
        title, body = format_event('PermissionRequest', {'tool_name': 'Bash', 'tool_input': {
            'description': '安装项目所需 Pillow', 'command': 'python -m pip install Pillow'}})
        self.assertIn('允许', title)
        self.assertIn('安装项目所需 Pillow', body)
        self.assertIn('python -m pip install Pillow', body)

    def test_question_formats(self):
        for tool, args in [('request_user_input', {'questions': [
            {'question': '选择部署环境？', 'options': [{'label': '测试'}, {'label': '生产'}]}]}),
                           ('functions.request_user_input_async', {'questions': [
            {'title': '选择部署环境？', 'options': ['测试', '生产']}]})]:
            result = format_event('PreToolUse', {'tool_name': tool, 'tool_input': args})
            self.assertIn('选择部署环境？', result[1])
            self.assertIn('测试 / 生产', result[1])

    def test_approval_without_commands(self):
        title, body = format_event('PermissionRequest', {'tool_name': 'Bash', 'tool_input': {
            'description': '处理 D:/private/report.csv 文件', 'command': 'echo private-command'}}, include_commands=False)
        self.assertNotIn('private-command', body)
        self.assertNotIn('report.csv', body)

    def test_plain_reply_question(self):
        title, body = format_event('Stop', {'last_assistant_message': '你希望部署到测试环境还是生产环境？'})
        self.assertEqual(title, 'Codex 询问')
        self.assertIn('生产环境', body)

    def test_other_tools_ignored(self):
        self.assertIsNone(format_event('PreToolUse', {'tool_name': 'Bash', 'tool_input': {'command': 'echo x'}}))

    def test_redaction_and_limit(self):
        self.assertNotIn('secret123', clean('api_key=secret123'))
        self.assertNotIn('abcXYZ', clean('Bearer abcXYZ'))
        self.assertEqual(len(format_event('Stop', {'last_assistant_message': '完成' * 500}, 120)[1]), 120)

    def test_distinct_requests_and_retries(self):
        calls = []
        def sender(*args):
            calls.append(args)
            print('{"id":"offline-test"}')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            payload = {'session_id': 's', 'turn_id': 't', 'tool_input': {'command': 'one'}}
            self.assertEqual(deliver('PermissionRequest', payload, DEFAULTS, root, sender), 'sent')
            self.assertEqual(deliver('PermissionRequest', payload, DEFAULTS, root, sender), 'duplicate')
            payload['tool_input']['command'] = 'two'
            self.assertEqual(deliver('PermissionRequest', payload, DEFAULTS, root, sender), 'sent')
            self.assertEqual(len(calls), 2)
            body = (root / 'logs/hook-delivery.log').read_text(encoding='utf-8')
            self.assertNotIn('one', body)
            def fail(*args):
                raise OSError('offline')
            payload['tool_input']['command'] = 'three'
            with self.assertRaises(OSError):
                deliver('PermissionRequest', payload, DEFAULTS, root, fail)
            self.assertEqual(deliver('PermissionRequest', payload, DEFAULTS, root, sender), 'sent')

    def test_stdout_does_not_approve(self):
        path = Path(__file__).parent / 'codex_notify_hook.py'
        run = subprocess.run([sys.executable, str(path), 'PreToolUse'],
                             input=json.dumps({'tool_name': 'Bash'}),
                             text=True, capture_output=True, timeout=5)
        self.assertEqual(run.returncode, 0)
        self.assertEqual(json.loads(run.stdout), {})

    def test_question_fallback_and_hook_dedupe(self):
        calls = []
        with tempfile.TemporaryDirectory() as folder:
            payload = {'session_id': 'same-session', 'turn_id': '', 'tool_name': 'request_user_input_async',
                       'tool_input': {'questions': [{'title': '现在部署吗？', 'options': ['部署', '暂缓']}]}}
            sender = lambda *args: calls.append(args)
            self.assertEqual(deliver('PreToolUse', payload, DEFAULTS, Path(folder), sender), 'sent')
            payload['turn_id'] = 'native-turn'
            self.assertEqual(deliver('PreToolUse', payload, DEFAULTS, Path(folder), sender), 'duplicate')
            payload['tool_input']['questions'][0]['title'] = '现在运行测试吗？'
            self.assertEqual(deliver('PreToolUse', payload, DEFAULTS, Path(folder), sender), 'sent')
            self.assertEqual(len(calls), 2)

    def test_failure_audit_omits_message_command_and_secrets(self):
        from codex_notify_hook import audit_status
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audit_status('Stop', {'session_id': 's', 'turn_id': 't',
                                 'last_assistant_message': 'private-body',
                                 'tool_input': {'command': 'secret-command'}},
                         'failed', 'TimeoutError', root)
            raw = (root / 'logs/hook-delivery.log').read_text(encoding='utf-8')
            self.assertNotIn('private-body', raw)
            self.assertNotIn('secret-command', raw)
            self.assertEqual(json.loads(raw)['error_type'], 'TimeoutError')

    def test_completion_fallback_and_native_hook_send_once(self):
        calls = []
        with tempfile.TemporaryDirectory() as folder:
            config = dict(DEFAULTS, only_user_thread_completions=True)
            context = lambda p: {'known': True, 'thread_source': 'user', 'originator': 'Codex Desktop'}
            payload = {'session_id': 'same-session', 'last_assistant_message': '完成正文',
                       'notification_route': 'completion-fallback'}
            sender = lambda *args: calls.append(args)
            self.assertEqual(deliver('Stop', payload, config, Path(folder), sender, context), 'sent')
            payload.update(turn_id='native-turn', notification_route='hook')
            self.assertEqual(deliver('Stop', payload, config, Path(folder), sender, context), 'duplicate')
            payload['last_assistant_message'] = '另一个完成结果'
            self.assertEqual(deliver('Stop', payload, config, Path(folder), sender, context), 'sent')
            self.assertEqual(len(calls), 2)

    def test_muting_raw_approval_preserves_completion_and_questions(self):
        config = dict(DEFAULTS, permission_notifications=False)
        sent = []
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sender = lambda *args: sent.append(args)
            payload = {'tool_name': 'Bash', 'tool_input': {'command': 'echo approval'}}
            self.assertEqual(deliver('PermissionRequest', payload, config, root, sender), 'suppressed')
            self.assertEqual(sent, [])
            self.assertEqual(deliver('Stop', {'last_assistant_message': '修复完成'}, config, root, sender), 'sent')
            question = {'tool_name': 'request_user_input_async', 'tool_input': {
                'questions': [{'title': '确认部署吗？', 'options': ['确认', '暂缓']}]}}
            self.assertEqual(deliver('PreToolUse', question, config, root, sender), 'sent')
            self.assertEqual(len(sent), 2)


if __name__ == '__main__':
    unittest.main()
