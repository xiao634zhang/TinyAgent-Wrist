import unittest
from training_monitor import evaluate

CFG = {'stale_seconds': 300, 'stall_seconds': 900, 'loss_spike_ratio': 10}


class MonitorTests(unittest.TestCase):
    def snapshot(self, **kw):
        return dict(run_id='test', status='TRAINING', phase='stage1',
                    stages={'stage1': {'step': 100, 'loss': .1}}, **kw)

    def test_initial_healthy(self):
        issues, obs = evaluate(self.snapshot(), {}, 1000, CFG)
        self.assertEqual(issues, {})
        self.assertEqual(obs['last_move'], 1000)

    def test_stalled_steps_even_if_updated_timestamp_changes(self):
        _, obs = evaluate(self.snapshot(updated_unix=1000), {}, 1000, CFG)
        issues, _ = evaluate(self.snapshot(updated_unix=2000), obs, 2000, CFG)
        self.assertIn('stalled', issues)

    def test_stage_switch_and_new_run_reset_stall(self):
        _, obs = evaluate(self.snapshot(), {}, 1000, CFG)
        d = self.snapshot(); d['run_id'] = 'new'
        self.assertNotIn('stalled', evaluate(d, obs, 9999, CFG)[0])
        d['run_id'] = 'test'; d['phase'] = 'stage2'
        self.assertNotIn('stalled', evaluate(d, obs, 9999, CFG)[0])

    def test_remote_clock_offset_does_not_mark_stale(self):
        d = self.snapshot(updated_unix=1, local_now_unix=1000, watcher={'updated_unix': 990, 'status': 'CONNECTED'})
        self.assertNotIn('connection', evaluate(d, {}, 1000, CFG)[0])

    def test_loss_nan_and_spike(self):
        d = self.snapshot(); d['stages']['stage1']['loss'] = float('nan')
        self.assertIn('loss:stage1:loss', evaluate(d, {}, 1000, CFG)[0])
        curves = {'stage1': [{'loss': v} for v in [.1]*20 + [2, 3, 2]]}
        self.assertIn('loss:stage1:spike', evaluate(self.snapshot(), {}, 1000, CFG, curves)[0])
        curves['stage1'][-2]['loss'] = .1
        self.assertNotIn('loss:stage1:spike', evaluate(self.snapshot(), {}, 1000, CFG, curves)[0])

    def test_gpu_error(self):
        self.assertIn('gpu-error', evaluate(self.snapshot(error='CUDA out of memory'), {}, 1000, CFG)[0])

    def test_finished_is_not_stalled_or_connection_error(self):
        d = self.snapshot(); d['status'] = 'TRAINING_COMPLETE'; d['watcher'] = {'status': 'RECONNECTING'}
        issues, _ = evaluate(d, {'run': 'test', 'phase': 'stage1', 'steps': {'stage1': 100}, 'last_move': 1}, 9999, CFG)
        self.assertIn('finished', issues)
        self.assertNotIn('stalled', issues)
        self.assertNotIn('connection', issues)

    def test_old_stage_completions_are_baseline(self):
        d = self.snapshot(); d['stages']['old'] = {'completion': {'completion_reason': 'EARLY_STOP'}}
        self.assertNotIn('stage:old', evaluate(d, {}, 1000, CFG)[0])
        _, old = evaluate(self.snapshot(), {}, 1000, CFG)
        self.assertIn('stage:old', evaluate(d, old, 1100, CFG)[0])


if __name__ == '__main__':
    unittest.main()
