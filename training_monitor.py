"""Read-only dashboard checks; only incident transitions publish through ntfy."""
import argparse
import contextlib
import io
import json
import math
import statistics
import time
import urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parent
COMPLETE = {'TRAINING_COMPLETE', 'TRAINING_AND_EVALUATION_COMPLETE',
            'WAITING_LOCAL_ARCHIVE_ACK', 'LOCAL_ARCHIVED_SHUTDOWN',
            'READY_FOR_LOCAL_ARCHIVE', 'WAITING_FOR_LOCAL_ARCHIVE',
            'COMPLETE_SHUTDOWN_ISSUED', 'COMPLETE', 'COMPLETED', 'SUCCEEDED'}
POST_TRAIN = COMPLETE | {'EVALUATING', 'VERIFYING', 'PACKAGING'}
FAILED = {'FAILED', 'ERROR', 'CRASHED', 'ABORTED'}


def fetch(url):
    # Local pages must not travel through an Internet proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=10) as response:
        return json.load(response)


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def evaluate(data, previous, now, settings, curves=None):
    """Returns current incidents plus a compact next observation; no side effects."""
    issues = {}
    run = str(data.get('run_id') or 'unknown')
    old = previous if previous.get('run') == run else {}
    status = str(data.get('status', '')).upper()
    watcher = data.get('watcher') or {}
    watch_status = str(watcher.get('status', '')).upper()
    phase = str(data.get('phase', ''))
    stages = data.get('stages') or {}
    progress = {k: s.get('step', 0) for k, s in stages.items()}
    changed = progress != old.get('steps') or phase != old.get('phase')
    last_move = now if changed else old.get('last_move', now)
    terminal = status in POST_TRAIN or watch_status == 'COMPLETE_SHUTDOWN_ISSUED'
    if status in COMPLETE or watch_status == 'COMPLETE_SHUTDOWN_ISSUED':
        issues['finished'] = f'训练已完成；状态 {status}；进度 {data.get("completed_steps", "?")}/{data.get("total_steps", "?")}。'
    elif status in {'EVALUATING', 'VERIFYING', 'PACKAGING'}:
        issues['finished'] = f'训练阶段结束，当前 {status}，评估/归档可能尚未完成。'
    if status in FAILED:
        issues['failed'] = f'训练异常退出：{status}。'
    errors = [str(data.get('error') or ''), str(watcher.get('error') or '')]
    for key, stage in stages.items():
        if str(stage.get('status', '')).upper() in FAILED:
            issues[f'failed:{key}'] = f'阶段 {key} 异常退出：{stage.get("status")}。'
        errors.append(str(stage.get('error') or ''))
        # Stage completions from before monitoring are baseline, not new events.
        if old and stage.get('completion') and not old.get('completed', {}).get(key):
            issues[f'stage:{key}'] = f'阶段 {key} 完成；原因 {(stage.get("completion") or {}).get("completion_reason", "完成")}。'
    message = '; '.join(e for e in errors if e)
    if message:
        low = message.lower()
        gpu_error = any(t in low for t in ('cuda', 'out of memory', 'nvidia', 'gpu', 'device-side', 'cublas', 'cudnn', 'xid'))
        issues['gpu-error' if gpu_error else 'reported-error'] = ('GPU/CUDA 报错：' if gpu_error else '看板报告错误：') + message[:240]
    # Watcher timestamps are local. Remote training clocks may have an offset.
    local_now = data.get('local_now_unix', now)
    watch_time = watcher.get('updated_unix')
    if not terminal and (watch_status.startswith('RECONNECT') or
                         (number(watch_time) and local_now - watch_time > settings['stale_seconds'])):
        issues['connection'] = f'训练采集连接异常/过期：{watch_status or "未提供状态"}。'
    if not terminal and status not in FAILED and now - last_move >= settings['stall_seconds']:
        issues['stalled'] = f'各阶段 step 已连续 {int((now-last_move)/60)} 分钟未推进，当前 {phase}/{status}；需检查 GPU 或训练进程。'
    for key, stage in stages.items():
        # Check only the active/in-progress stage, not completed historical losses.
        if key != phase and str(stage.get('status', '')).upper() != 'TRAINING':
            continue
        if stage.get('completion') or terminal:
            continue
        for metric in ('loss', 'reconstruction'):
            value = stage.get(metric)
            if value is not None and (not number(value) or not math.isfinite(value)):
                issues[f'loss:{key}:{metric}'] = f'{key} 的 {metric} 非有限值：{value}，step {stage.get("step")}。'
        points = (curves or {}).get(key, [])
        values = [p.get('loss') for p in points]
        if any(number(v) and not math.isfinite(v) for v in values):
            issues[f'loss:{key}:history'] = f'{key} 最近 Loss 日志出现 NaN/Inf。'
        finite = [abs(v) for v in values if number(v) and math.isfinite(v)]
        if len(finite) >= 23:
            baseline = statistics.median(finite[:-3])
            if baseline > 1e-12 and all(v > settings['loss_spike_ratio'] * baseline for v in finite[-3:]):
                issues[f'loss:{key}:spike'] = f'{key} 连续3个 Loss 超过此前中位数 {settings["loss_spike_ratio"]} 倍；最新 {finite[-1]:.6g}，基线 {baseline:.6g}，请检查。'
    return issues, {'run': run, 'phase': phase, 'status': status, 'steps': progress,
                    'last_move': last_move, 'completed': {k: bool(s.get('completion')) for k, s in stages.items()}}


def collect(target):
    result = {'target': target}
    try:
        data = fetch(target['url'].rstrip('/') + '/api/progress')
        curves, warnings = {}, []
        if str(data.get('status', '')).upper() not in POST_TRAIN:
            for key, stage in (data.get('stages') or {}).items():
                if stage.get('completion'):
                    continue
                if key == data.get('phase') or str(stage.get('status', '')).upper() == 'TRAINING':
                    from urllib.parse import urlencode
                    try:
                        curve = fetch(target['url'].rstrip('/') + '/api/loss?' + urlencode({'stage': key, 'recent': 100}))
                        curves[key] = curve.get('points', [])
                    except Exception as exc:
                        warnings.append(f'Loss曲线读取失败：{type(exc).__name__}')
        result.update(data=data, curves=curves, warnings=warnings)
    except Exception as exc:
        result['error'] = type(exc).__name__
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--notify', action='store_true', help='Publish new alerts; default is a dry run')
    args = parser.parse_args()
    config = json.loads((ROOT / 'training_monitor_config.json').read_text(encoding='utf-8-sig'))
    state_path = ROOT / 'logs/training-monitor-state.json'
    state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
    now = time.time()
    reports = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(collect, config['targets']))
    for item in results:
        target = item['target']; key = target['url']; old = state.get(key, {})
        if item.get('error'):
            failures = old.get('fetch_failures', 0) + 1
            observation = dict(old, fetch_failures=failures)
            issues = {'unreachable': f'本地训练看板连续 {failures} 次无法访问（{item["error"]}），不能确认远端训练状态。'} if failures >= 2 else {}
        else:
            issues, observation = evaluate(item['data'], old, now, config, item['curves'])
            if item['warnings']:
                issues['loss-unavailable'] = '; '.join(item['warnings'])
            observation['fetch_failures'] = 0
        # Retry unsent durable events even if the next snapshot has moved on.
        if old.get('run') == observation.get('run'):
            for pending_kind, pending_detail in old.get('pending', {}).items():
                issues.setdefault(pending_kind, pending_detail)
        # A completion is a durable event. Transient issues notify once per incident,
        # again only after recovery. No routine status messages.
        run = observation.get('run', old.get('run', 'unknown'))
        sent = dict(old.get('sent', {}))
        active = set(old.get('active', []))
        for kind, detail in issues.items():
            event_key = run + ':' + kind
            durable = kind == 'finished' or kind.startswith('stage:')
            if event_key in sent and (durable or kind in active):
                continue
            body = f'{target["name"]}（{key}）\n{detail}'
            if run != 'unknown': body += f'\n运行：{run}'
            record = {'target': key, 'kind': kind, 'message': body, 'sent': False}
            if args.notify:
                try:
                    from send_notification import send
                    from codex_notify_hook import clean
                    receipt = io.StringIO()
                    with contextlib.redirect_stdout(receipt):
                        send(config['server'], config['topic'], clean(body)[:420], title='训练完成' if durable else '训练异常提醒')
                    record['receipt'] = json.loads(receipt.getvalue())
                    sent[event_key] = now
                    record['sent'] = True
                except Exception as exc:
                    sent.pop(event_key, None)
                    record['send_error'] = type(exc).__name__
            reports.append(record)
        observation['sent'] = sent
        observation['pending'] = {k: v for k, v in issues.items()
                                  if (k == 'finished' or k.startswith('stage:'))
                                  and run + ':' + k not in sent}
        observation['active'] = list(issues)
        observation['checked_unix'] = now
        state[key] = observation
    summary = {'checked_unix': now, 'notify': args.notify, 'alerts': reports,
               'targets': [{**x['target'], 'reachable': 'error' not in x,
                            'status': x.get('data', {}).get('status'),
                            'phase': x.get('data', {}).get('phase'),
                            'steps': {k: s.get('step') for k,s in x.get('data', {}).get('stages', {}).items()}}
                           for x in results],
               'gpu_coverage': 'GPU/CUDA errors reported by dashboards and stalled steps; hardware telemetry is not exposed.'}
    log_dir = ROOT / 'logs'; log_dir.mkdir(exist_ok=True)
    if args.notify:
        temp = state_path.with_suffix('.tmp')
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(state_path)
        with (log_dir / 'training-monitor.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(summary, ensure_ascii=False) + '\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
