"""Send the exact final reply before rendering it; shares Stop-hook deduplication."""
import argparse
import json
import os
from pathlib import Path
from codex_notify_hook import ROOT, DEFAULTS, audit_status, deliver


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', type=Path, required=True, help='Exact final reply, UTF-8 text')
    args = parser.parse_args()
    payload = {'session_id': os.environ.get('CODEX_THREAD_ID', os.environ.get('CODEX_SESSION_ID', '')),
               'last_assistant_message': args.file.read_text(encoding='utf-8-sig'),
               'notification_route': 'completion-fallback'}
    try:
        config = dict(DEFAULTS)
        config.update(json.loads((ROOT / 'notification_config.json').read_text(encoding='utf-8-sig')))
        audit_status('Stop', payload, 'started')
        result = deliver('Stop', payload, config)
        print('Completion notification: ' + result)
        return 0 if result in ('sent', 'duplicate') else 2
    except Exception as exc:
        audit_status('Stop', payload, 'failed', type(exc).__name__)
        print('Completion notification failed: ' + type(exc).__name__)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
