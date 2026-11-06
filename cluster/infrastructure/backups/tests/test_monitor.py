import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('monitor', Path(__file__).resolve().parents[1] / 'backup-monitor.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
NOW = m.timestamp('2026-11-06T12:00:00Z')
CRON = {'spec': {'suspend': False}}

def job(kind, when, uid='test', diagnostic=False):
    return {'metadata': {'name': 'immich-backup-test', 'uid': uid, 'creationTimestamp': when},
            'spec': {'template': {'spec': {'containers': [{'command': ['diagnostic' if diagnostic else '/scripts/backup-postgres.sh'], 'env': [{'name': 'APP', 'value': 'immich'}]}]}}},
            'status': {'conditions': [{'type': kind, 'status': 'True', 'lastTransitionTime': when}]}}

class MonitorTests(unittest.TestCase):
    def evaluate(self, jobs=(), previous=None, cron=CRON):
        return m.evaluate('immich', cron, jobs, previous or {}, NOW)[0]
    def test_manual_success_and_historical_failure(self):
        result=self.evaluate([job('Failed','2026-11-06T09:00:00Z'),job('Complete','2026-11-06T10:00:00Z')])
        self.assertEqual(result['key'],'healthy')
    def test_new_failure_and_pruned_job(self):
        result=self.evaluate([job('Failed','2026-11-06T11:00:00Z')])
        self.assertEqual(result['key'],'failed:test')
        self.assertEqual(self.evaluate(previous=result)['key'],'failed:test')
        self.assertEqual(self.evaluate([job('Complete','2026-11-06T11:30:00Z')],result)['key'],'healthy')
    def test_stale_and_startup_grace(self):
        self.assertEqual(self.evaluate()['key'],'healthy')
        self.assertEqual(self.evaluate(previous={'first_seen':NOW-27*3600})['key'],'stale')
        self.assertEqual(self.evaluate(previous={'last_success':NOW-27*3600})['key'],'stale')
    def test_missing_suspended_and_diagnostic(self):
        self.assertEqual(self.evaluate(cron=None)['key'],'missing')
        self.assertEqual(self.evaluate(cron={'spec':{'suspend':True}})['key'],'suspended')
        self.assertEqual(self.evaluate([job('Failed','2026-11-06T11:00:00Z',diagnostic=True)])['key'],'healthy')
    def test_k3s_failure_then_success(self):
        self.assertIn('k3s', m.APPS)
        failed=job('Failed','2026-11-06T09:00:00Z')
        success=job('Complete','2026-11-06T10:00:00Z')
        for item in (failed,success):
            item['spec']['template']['spec']['containers'][0]['command']=['python','-B','/scripts/backup-k3s.py']
        result=m.evaluate('k3s',CRON,[failed,success],{},NOW)[0]
        self.assertEqual(result['key'],'healthy')
        self.assertEqual(result['last_success'],m.timestamp('2026-11-06T10:00:00Z'))
        self.assertEqual(m.evaluate('tiastube',CRON,[failed,success],{},NOW)[0]['last_success'],0)
    def test_delivery_failure_does_not_save_state(self):
        calls=[]
        def api(path, body=None):
            calls.append((path,body))
            if path==m.STATE:return {'metadata':{'resourceVersion':'1'}}
            return {'items':[]}
        with patch.object(m,'api',side_effect=api),patch.object(m,'discord',side_effect=RuntimeError('delivery failed')):
            with self.assertRaises(RuntimeError):m.main()
        self.assertTrue(all(body is None for _,body in calls))

if __name__=='__main__':unittest.main()
