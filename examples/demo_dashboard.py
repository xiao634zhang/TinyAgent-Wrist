"""Synthetic localhost-only dashboard; never reads real training data."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import time
from urllib.parse import urlparse


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--port', type=int, default=9876)
    p.add_argument('--mode', choices=['healthy', 'complete', 'gpu-error', 'nan', 'stall'], default='healthy')
    a = p.parse_args(); started = time.time()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlparse(self.path).path
            step = 100 if a.mode == 'stall' else 100 + int(time.time() - started)
            if path == '/api/progress':
                value = {'method': 'Example', 'run_id': 'synthetic-demo-' + a.mode,
                         'status': 'TRAINING_COMPLETE' if a.mode == 'complete' else 'TRAINING',
                         'phase': 'stage1', 'completed_steps': step, 'total_steps': 1000,
                         'local_now_unix': time.time(), 'watcher': {'status': 'CONNECTED', 'updated_unix': time.time()},
                         'stages': {'stage1': {'step': step, 'loss': 'NaN' if a.mode == 'nan' else .1}}}
                if a.mode == 'gpu-error': value['error'] = 'Synthetic CUDA out of memory (demo only)'
            elif path == '/api/loss':
                value = {'points': [{'step': x, 'loss': .1} for x in range(max(0, step-99), step+1)]}
            else:
                self.send_error(404); return
            body = json.dumps(value).encode()
            self.send_response(200); self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
        def log_message(self, *args): pass
    print(f'Synthetic demo: http://127.0.0.1:{a.port}, mode={a.mode}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', a.port), Handler).serve_forever()


if __name__ == '__main__': main()
