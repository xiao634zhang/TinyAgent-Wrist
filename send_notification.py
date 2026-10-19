"""Publish a test message only to an explicitly chosen ntfy server/topic."""
import argparse
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent


def ipv6_address():
    """Cache only public DNS data. No notification content goes to the resolver."""
    cache = ROOT / 'logs' / 'ntfy-dns-cache.json'
    try:
        stored = json.loads(cache.read_text(encoding='utf-8'))
        if stored['expires'] > time.time():
            return stored['address']
    except (OSError, ValueError, KeyError):
        pass
    with urllib.request.urlopen('https://dns.google/resolve?name=ntfy.sh&type=AAAA', timeout=4) as response:
        records = json.load(response)
    import ipaddress
    for answer in records.get('Answer', []):
        if answer.get('type') == 28:
            address = str(ipaddress.IPv6Address(answer['data']))
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({'address': address,
                                         'expires': time.time() + min(int(answer.get('TTL', 300)), 7200)}), encoding='utf-8')
            return address
    raise RuntimeError('No ntfy IPv6 DNS record')


def via_ipv6(server, data):
    curl = shutil.which('curl.exe') or shutil.which('curl')
    if not curl:
        raise RuntimeError('curl not found for IPv6 fallback')
    address = ipv6_address()
    command = [curl, '--silent', '--show-error', '--fail-with-body',
               '--connect-timeout', '4', '--max-time', '8',
               '--connect-to', f'ntfy.sh:443:[{address}]:443',
               '--header', 'Content-Type: application/json', '--data-binary', '@-', server.rstrip('/')]
    proxy = urllib.request.getproxies().get('https')
    if proxy:
        command[1:1] = ['--proxy', proxy]
    run = subprocess.run(command, input=data, capture_output=True, timeout=10)
    if run.returncode:
        # Avoid logging the body, headers or proxy credentials.
        raise RuntimeError(f'ntfy IPv6 transport failed (curl {run.returncode})')
    return json.loads(run.stdout)


def send(server, topic, message, title='Codex test'):
    parsed = urlparse(server)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError('Use an HTTPS ntfy server without credentials in the URL')
    if not isinstance(topic, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', topic):
        raise ValueError('Configure your own ntfy topic (letters, digits, underscores, hyphens).')
    token = os.environ.get('NTFY_TOKEN', '')
    if '\r' in token or '\n' in token:
        raise ValueError('Invalid NTFY_TOKEN')
    data = json.dumps({'topic': topic, 'title': title, 'message': message,
                       'priority': 4}).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(server.rstrip('/'), data=data, headers=headers)
    transport = 'default'
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            result = json.load(response)
    except (TimeoutError, OSError) as exc:
        # HTTP errors are server responses, not connection failures: do not republish.
        from urllib.error import HTTPError
        if token or isinstance(exc, HTTPError) or parsed.hostname != 'ntfy.sh' or parsed.port not in (None, 443):
            raise
        result = via_ipv6(server, data)
        transport = 'ipv6-fallback'
    receipt = {k: result.get(k) for k in ('id', 'time', 'event')}
    receipt['transport'] = transport
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--server', required=True, help='Match the server shown in the phone subscription')
    p.add_argument('--topic', required=True)
    p.add_argument('--message', default='Codex notification test')
    p.add_argument('--title', default='Codex test')
    a = p.parse_args()
    send(a.server, a.topic, a.message, a.title)
