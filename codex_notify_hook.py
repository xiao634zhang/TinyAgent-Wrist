"""Content notifications for Codex desktop/VS Code. Never approves operations."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from send_notification import send

ROOT = Path(__file__).resolve().parent
QUESTION_TOOL = re.compile(r'request_user_input|ask_user_question|AskUserQuestion', re.I)
DEFAULTS = {'server': 'https://ntfy.sh', 'topic': '',
            'max_chars': 420, 'dedupe_seconds': 60, 'include_commands': True,
            'permission_notifications': True}


def session_context(payload):
    """Read only this hook session's classification, never chat contents."""
    session_id = payload.get('session_id')
    if not session_id:
        return {'known': False}
    home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    db_path = home / 'state_5.sqlite'
    if not db_path.exists():
        return {'known': False}
    try:
        with sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True, timeout=0.5) as db:
            row = db.execute('SELECT source,originator,thread_source FROM threads WHERE id=?', (session_id,)).fetchone()
        if row:
            return {'known': True, 'source': row[0], 'originator': row[1], 'thread_source': row[2]}
    except sqlite3.Error:
        return {'known': False, 'lookup_error': True}
    return {'known': False}


def suppression_reason(event, payload, config, context):
    if event == 'PermissionRequest' and not config.get('permission_notifications', True):
        return 'raw-approval-request-muted'
    if event == 'Stop' and config.get('only_user_thread_completions', False):
        try:
            generated = json.loads(payload.get('last_assistant_message') or '')
        except (TypeError, ValueError):
            generated = None
        if isinstance(generated, dict) and set(generated).issubset({'suggestion', 'suggestions'}) and generated:
            return 'composer-suggestion-payload'
        hints = ' '.join(str(context.get(k, '')) for k in ('source', 'originator', 'thread_source'))
        if re.search(r'suggest|predict|ambient', hints, re.I):
            return 'background-suggestion'
        if not context.get('known') or context.get('thread_source') != 'user':
            return 'not-a-user-thread-completion'
    return None


def clean(value):
    text = str(value or '')
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'```[^\n]*\n?', '', text).replace('`', '')
    text = re.sub(r'(?m)^\s{0,3}#{1,6}\s+', '', text)
    text = text.replace('**', '').replace('__', '')
    text = re.sub(r'(?im)(Bearer\s+)[A-Za-z0-9._~+/-]+', r'\1[已隐藏]', text)
    text = re.sub(r'(?i)((?:api[_-]?key|access[_-]?token|password|secret)\s*[=:]\s*)'
                  r'([\"\x27]?)[^\s,;\"\x27]+', r'\1[已隐藏]', text)
    return '\n'.join(line.strip() for line in text.strip().splitlines() if line.strip())


def tool_args(payload):
    args = payload.get('tool_input', {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return {'command': args}
    if not isinstance(args, dict):
        return {}
    if isinstance(args.get('arguments'), (dict, str)):
        nested = args['arguments']
        if isinstance(nested, str):
            try:
                nested = json.loads(nested)
            except ValueError:
                nested = None
        if isinstance(nested, dict):
            return nested
    return args


def format_event(event, payload, max_chars=420, include_commands=True):
    args = tool_args(payload)
    if event == 'Stop':
        title = 'Codex 完成'
        body = clean(payload.get('last_assistant_message'))
        if not body:
            body = '本轮已结束；运行时未提供回复正文，请在电脑查看。'
        elif re.search(r'[？?][\s。.!！]*$', body):
            # Plain-text questions sent without a question tool still reach the wrist.
            title = 'Codex 询问'
    elif event == 'PermissionRequest':
        title = 'Codex 请求允许'
        reason = args.get('description') or args.get('justification') or payload.get('description')
        operation = args.get('command') or args.get('cmd')
        parts = []
        if reason:
            reason_text = clean(reason)
            parts.append(reason_text[:200].rstrip() + ('…' if len(reason_text) > 200 else ''))
        if operation and include_commands:
            operation_text = clean(operation)
            parts.append('操作：' + operation_text[:160].rstrip() + ('…' if len(operation_text) > 160 else ''))
        if not parts:
            parts.append('请求执行：' + clean(payload.get('tool_name', '工具操作')))
            for key in (('title', 'path', 'url', 'query') if include_commands else ('title',)):
                if isinstance(args.get(key), str):
                    parts.append(f'{key}：{clean(args[key])}')
        body = '\n'.join(parts)
    elif event == 'PreToolUse' and QUESTION_TOOL.search(str(payload.get('tool_name', ''))):
        title = 'Codex 询问'
        parts = []
        for index, question in enumerate(args.get('questions', []), 1):
            if not isinstance(question, dict):
                continue
            text = question.get('question') or question.get('title') or question.get('header')
            if text:
                parts.append(f'{index}. {clean(text)}')
            options = []
            for option in question.get('options', []):
                label = option.get('label') if isinstance(option, dict) else option
                if label:
                    options.append(clean(label))
            if options:
                parts.append('选项：' + ' / '.join(options))
        if not parts:
            text = args.get('question') or args.get('prompt') or args.get('message')
            if text:
                parts.append(clean(text))
        if not parts:
            return None
        body = '\n'.join(parts)
    else:
        return None
    if not include_commands and event == 'PermissionRequest':
        body = re.sub(r'[A-Za-z]:[\\/][^\s，。；,;]+|(?<!\w)/(?:home|Users|mnt|tmp)/[^\s，。；,;]+', '[路径已省略]', body)
    limit = min(1800, max(80, int(max_chars)))
    if len(body) > limit:
        body = body[:limit - 1].rstrip() + '…'
    return title, body


def deliver(event, payload, config, root=ROOT, sender=send, context_loader=session_context):
    context = context_loader(payload) if event == 'Stop' or payload.get('session_id') else {}
    reason = suppression_reason(event, payload, config, context)
    if reason:
        log_dir = root / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / 'hook-delivery.log').open('a', encoding='utf-8') as log:
            log.write(json.dumps({'time': int(time.time()), 'event': event,
                                 'session_id': payload.get('session_id'),
                                 'context': context,
                                 'status': 'suppressed', 'reason': reason}, ensure_ascii=False) + '\n')
        return 'suppressed'
    formatted = format_event(event, payload, config['max_chars'], config.get('include_commands', True))
    if formatted is None:
        return 'ignored'
    title, message = formatted
    origin = os.environ.get('CODEX_INTERNAL_ORIGINATOR_OVERRIDE', '')
    if not origin:
        origin = str(context.get('originator') or '')
    if 'vscode' in origin.lower():
        title = title.replace('Codex ', 'Codex VSCode ', 1)
    identity = [event, payload.get('session_id', ''),
                '' if event in ('PreToolUse', 'Stop') else payload.get('turn_id', ''), title, message]
    key = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:32]
    state_dir = root / 'logs' / 'hook-state'
    state_dir.mkdir(parents=True, exist_ok=True)
    marker = state_dir / key
    if marker.exists() and time.time() - marker.stat().st_mtime < config['dedupe_seconds']:
        return 'duplicate'
    if marker.exists():
        marker.unlink(missing_ok=True)
    try:
        with marker.open('x') as stream:
            stream.write(str(time.time()))
    except FileExistsError:
        return 'duplicate'
    try:
        receipt = io.StringIO()
        with contextlib.redirect_stdout(receipt):
            sender(config['server'], config['topic'], message, title)
        with (root / 'logs/hook-delivery.log').open('a', encoding='utf-8') as log:
            log.write(json.dumps({'time': int(time.time()), 'event': event,
                                 'tool': payload.get('tool_name'), 'chars': len(message),
                                 'route': payload.get('notification_route', 'hook'),
                                 'session_id': payload.get('session_id'), 'context': context,
                                 'client': 'vscode' if 'vscode' in origin.lower() else 'unspecified',
                                 'delivery': receipt.getvalue().strip()}, ensure_ascii=False) + '\n')
    except Exception:
        marker.unlink(missing_ok=True)
        raise
    return 'sent'


def main():
    event = sys.argv[1] if len(sys.argv) > 1 else ''
    payload = {}
    try:
        payload = json.load(sys.stdin)
        config = dict(DEFAULTS)
        config_path = ROOT / 'notification_config.json'
        if config_path.exists():
            config.update(json.loads(config_path.read_text(encoding='utf-8-sig')))
        if '--preview' in sys.argv:
            print(json.dumps(format_event(event, payload, config['max_chars'], config.get('include_commands', True)), ensure_ascii=False), file=sys.stderr)
        else:
            # Record entry before network I/O. No reply/question/command bodies.
            audit_status(event, payload, 'started')
            deliver(event, payload, config)
    except Exception as exc:
        try:
            audit_status(event, payload, 'failed', type(exc).__name__)
        except OSError:
            pass
        print(f'Codex notification: {type(exc).__name__}', file=sys.stderr)
    finally:
        print('{}')


def audit_status(event, payload, status, error_type=None, root=ROOT):
    directory = root / 'logs'
    directory.mkdir(parents=True, exist_ok=True)
    record = {'time': int(time.time()), 'event': event, 'status': status}
    if isinstance(payload, dict):
        record.update(session_id=payload.get('session_id'), turn_id=payload.get('turn_id'))
    if error_type:
        record['error_type'] = error_type
    with (directory / 'hook-delivery.log').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
