"""Generate machine-local config; hook installation is explicit and preserves others."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import secrets
import sys

ROOT = Path(__file__).resolve().parent


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def definitions(root, python):
    # Reject shell metacharacters that cannot be quoted safely in these two shells.
    for value in (root, python):
        if any(c in str(value) for c in ('"', '$', '`', '\r', '\n')):
            raise ValueError('Use an install path without quotes, $, backticks or newlines.')
    events = {}
    for event in ('Stop', 'PermissionRequest', 'PreToolUse'):
        script = root / 'codex_notify_hook.py'
        cmd = f'"{python}" -X utf8 "{script}" {event}'
        group = {'hooks': [{'type': 'command', 'command': cmd, 'commandWindows': '& ' + cmd, 'timeout': 25}]}
        if event == 'PreToolUse':
            group['matcher'] = 'request_user_input|ask_user_question|AskUserQuestion'
        events[event] = [group]
    return events


def merge_hooks(existing, generated):
    hooks = existing.setdefault('hooks', {})
    for event, groups in generated.items():
        dest = hooks.setdefault(event, [])
        for group in groups:
            if group not in dest:
                dest.append(group)
    return existing


def rules(root, python):
    return f'''<!-- tinyagent-wrist:start -->
## Codex phone notifications (explicit content opt-in)
The user has opted in to forwarding final replies and questions to their configured ntfy server/topic.
Before asking a question, save the exact questions/options as UTF-8 JSON with a top-level questions array, then run:
`"{python}" -X utf8 "{root / 'notify_question.py'}" --file <questions-file>`
Before a final reply, save that exact final reply as UTF-8 text, then run:
`"{python}" -X utf8 "{root / 'notify_completion.py'}" --file <reply-file>`
In PowerShell prefix the quoted executable with `&`. Keep text in files, never interpolate it as executable shell code.
Still display the original question/reply. Notification delivery is not a user answer or approval.
If sending fails, continue the conversation and disclose the failure; do not retry indefinitely.
Only applies when these local paths exist. Do not send internal analysis, composer suggestions, cookies, tokens or passwords.
Native hooks and fallbacks share short-window deduplication; hooks never approve operations.
<!-- tinyagent-wrist:end -->
'''


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--topic', help='Omit to generate a random topic, saved locally only')
    p.add_argument('--server', default='https://ntfy.sh')
    p.add_argument('--install-hooks', action='store_true')
    p.add_argument('--install-rules', action='store_true', help='Opt in to forwarding final reply and question contents')
    p.add_argument('--codex-home', type=Path, default=Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))))
    a = p.parse_args()
    config_path = ROOT / 'notification_config.json'
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding='utf-8-sig'))
        if a.topic and a.topic != config['topic']:
            p.error('Existing config preserved; edit notification_config.json locally to change topic.')
    else:
        topic = a.topic or 'codex-' + secrets.token_hex(16)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', topic) or topic.startswith('REPLACE_'):
            p.error('Provide a valid personal topic, not the example placeholder.')
        from urllib.parse import urlparse
        url = urlparse(a.server)
        if url.scheme != 'https' or not url.netloc or url.username or url.password or url.query or url.fragment:
            p.error('Server must be an HTTPS URL without credentials/query/fragment.')
        config = json.loads((ROOT / 'notification_config.example.json').read_text(encoding='utf-8'))
        config.update(server=a.server, topic=topic)
        save(config_path, config)
    training_path = ROOT / 'training_monitor_config.json'
    if not training_path.exists():
        training = json.loads((ROOT / 'training_monitor_config.example.json').read_text(encoding='utf-8'))
        training.update(server=config['server'], topic=config['topic'])
        save(training_path, training)
    generated = definitions(ROOT, Path(sys.executable).resolve())
    save(ROOT / 'hooks.generated.json', {'hooks': generated})
    rule_text = rules(ROOT, Path(sys.executable).resolve())
    (ROOT / 'fallback-rules.generated.md').write_text(rule_text, encoding='utf-8')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    if a.install_hooks:
        file = a.codex_home / 'hooks.json'
        old = json.loads(file.read_text(encoding='utf-8-sig')) if file.exists() else {}
        if file.exists():
            save(ROOT / f'logs/hooks-backup-{stamp}.json', old)
        save(file, merge_hooks(old, generated))
        print('Hooks merged. Review/trust them in Codex; trust hashes were not changed.')
    if a.install_rules:
        file = a.codex_home / 'AGENTS.md'; file.parent.mkdir(parents=True, exist_ok=True)
        original = file.read_text(encoding='utf-8-sig') if file.exists() else ''
        backup = ROOT / f'logs/AGENTS-backup-{stamp}.md'; backup.parent.mkdir(exist_ok=True)
        backup.write_text(original, encoding='utf-8')
        pattern = r'(?s)<!-- tinyagent-wrist:start -->.*?<!-- tinyagent-wrist:end -->\n?'
        updated = re.sub(pattern, lambda _: rule_text, original) if re.search(pattern, original) else original.rstrip() + '\n\n' + rule_text
        file.write_text(updated, encoding='utf-8')
        print('Content forwarding rules installed; reload/resume the Codex conversation if needed.')
    print('Local configuration generated. Read notification_config.json locally for your topic; subscribe to it on your phone.')


if __name__ == '__main__':
    main()
