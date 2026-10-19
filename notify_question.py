"""Pre-question fallback for clients whose async question tools skip hooks."""
import argparse
import json
import os
from pathlib import Path
import sys
from codex_notify_hook import DEFAULTS, ROOT, deliver


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', type=Path, help='UTF-8 JSON file containing the exact questions payload')
    args = parser.parse_args()
    try:
        if args.file:
            questions = json.loads(args.file.read_text(encoding='utf-8-sig'))
        else:
            questions = json.loads(sys.stdin.buffer.read().decode('utf-8-sig'))
        config = dict(DEFAULTS)
        config_path = ROOT / 'notification_config.json'
        if config_path.exists():
            config.update(json.loads(config_path.read_text(encoding='utf-8-sig')))
        payload = {'session_id': os.environ.get('CODEX_THREAD_ID', os.environ.get('CODEX_SESSION_ID', '')),
                   'tool_name': 'request_user_input_async', 'tool_input': questions,
                   'notification_route': 'question-fallback'}
        result = deliver('PreToolUse', payload, config)
        print('Question notification: ' + result)
        return 0 if result in ('sent', 'duplicate') else 2
    except Exception as exc:
        print('Question notification failed: ' + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
