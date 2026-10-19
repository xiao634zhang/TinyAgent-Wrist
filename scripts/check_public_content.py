"""Scan tracked/index content without printing secret values. Not a full DLP tool."""
from pathlib import Path
import re
import subprocess
import sys

RULES = {
    'github-token': re.compile(r'gh[pousr]_[A-Za-z0-9]{24,}|github_pat_[A-Za-z0-9_]{30,}'),
    'openai-like-key': re.compile(r'sk-(?:proj-)?[A-Za-z0-9_-]{30,}'),
    'private-key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'cookie-header': re.compile(r'(?im)^\s*Cookie\s*:\s*[^\s]+'),
    'windows-user-path': re.compile(r'(?i)[A-Z]:[\\/]+Users[\\/]+[A-Za-z0-9_.-]+'),
    'credential-url': re.compile(r'https?://[^\s/\"\x27:]+:[^\s/\"\x27@]+@'),
}
PRIVATE_NAMES = {'notification_config.json', 'training_monitor_config.json', 'hooks.generated.json',
                 'fallback-rules.generated.md', '.env'}


def findings(name, data):
    path = Path(name)
    problems = []
    if path.name in PRIVATE_NAMES or any(p in ('logs', '.venv', 'tools') for p in path.parts):
        problems.append('private-runtime-file')
    if path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.xml', '.db', '.sqlite', '.pem', '.key', '.zip'):
        problems.append('binary-or-private-artifact')
    if len(data) > 2_000_000:
        problems.append('oversized-file')
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        return problems + ['non-utf8-file']
    for label, rule in RULES.items():
        if rule.search(text): problems.append(label)
    return problems


def main():
    root = Path(__file__).resolve().parents[1]
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
    failed = []
    for name in filter(None, names):
        data = subprocess.check_output(['git', 'show', ':' + name], cwd=root)
        for label in findings(name, data): failed.append((name, label))
    for name, label in failed:
        print(f'{name}: {label}')
    print(f'Public content scan: {"FAIL" if failed else "PASS"}; {len(list(filter(None,names)))} tracked files; secret values omitted.')
    return 1 if failed else 0


if __name__ == '__main__': raise SystemExit(main())
