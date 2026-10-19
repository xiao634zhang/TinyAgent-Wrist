"""Single-instance background process, independent of Codex automations."""
import argparse
import json
import msvcrt
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
LOGS = ROOT / 'logs'


def write_status(value):
    dest = LOGS / 'training-watch-status.json'
    tmp = dest.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(dest)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--stop', action='store_true')
    p.add_argument('--interval', type=int, default=30)
    args = p.parse_args()
    LOGS.mkdir(exist_ok=True)
    stop = LOGS / 'training-watch.stop'
    if args.stop:
        stop.write_text('stop requested', encoding='utf-8')
        print('Stop requested; the current read-only check will finish first.')
        return
    if args.interval < 10:
        p.error('interval must be at least 10 seconds')
    with (LOGS / 'training-watch.lock').open('a+b') as lock:
        if lock.tell() == 0:
            lock.write(b'0'); lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            print('A training watcher is already running.')
            return
        stop.unlink(missing_ok=True)
        status = {'pid': os.getpid(), 'started_unix': time.time(), 'interval_seconds': args.interval}
        write_status(dict(status, state='starting'))
        try:
            while not stop.exists():
                started = time.time()
                try:
                    result = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'training_monitor.py'), '--notify'],
                                            capture_output=True, timeout=100,
                                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    payload = json.loads(result.stdout.decode('utf-8')) if result.returncode == 0 else None
                    current = dict(status, state='running' if payload else 'check_failed', checked_unix=time.time(),
                                   last_exit_code=result.returncode, summary=payload)
                    if result.returncode:
                        # No raw stderr: dependencies could emit credential-bearing messages.
                        current['error'] = 'monitor subprocess failed; see exit code'
                except Exception as exc:
                    current = dict(status, state='check_failed', checked_unix=time.time(), error=type(exc).__name__)
                write_status(current)
                if current['state'] != 'running':
                    with (LOGS / 'training-watch-errors.jsonl').open('a', encoding='utf-8') as stream:
                        stream.write(json.dumps(current, ensure_ascii=False) + '\n')
                # Poll the stop marker without keeping a terminal tool call open.
                while time.time() - started < args.interval and not stop.exists():
                    time.sleep(1)
        finally:
            write_status(dict(status, state='stopped', stopped_unix=time.time()))
            lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


if __name__ == '__main__':
    main()
