import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import apps
from lib.common import Failure

class Kube:
    def __init__(self, existing=None, owners=None):
        self.objects = existing or {}
        self.owners = owners or []
        self.writes = []
    def identity(self): pass
    def get(self, kind, name, namespace=None, **kw):
        return self.objects.get((kind.lower(), name))
    def call(self, *args, **kw):
        if 'get' in args: return json.dumps({'items': self.owners})
        obj = json.loads(kw['data'])
        self.writes.append(obj)
        self.objects[(obj['kind'].lower(), obj['metadata']['name'])] = obj
        return ''

OBJECTS = [{'apiVersion':'batch/v1', 'kind':'CronJob', 'metadata':{'name':'k3s-backup','namespace':'backups'}, 'spec':{'suspend':False}}]

class BackupSetupTests(unittest.TestCase):
    def test_infrastructure_discovery(self):
        self.assertIn('database-backups', apps.names())
        app, recorded = apps.application('database-backups')
        self.assertTrue(recorded)
        self.assertEqual(app['spec']['source']['path'], 'cluster/infrastructure/backups')
        refs = apps.secret_refs(apps.documents('database-backups'))
        self.assertEqual(refs[('backups','backup-discord')], {'webhook-url'})
        self.assertEqual(refs[('backups','immich-backup-db')], {'PGUSER','PGPASSWORD','PGDATABASE'})

    def test_stage_suspends_without_editing_manifests(self):
        objects = copy.deepcopy(OBJECTS)
        k = Kube()
        with patch('lib.apps.render', return_value=objects), patch('lib.apps.check', return_value=True), patch('lib.apps.confirm', return_value=True):
            apps.stage('database-backups', k)
        self.assertTrue(k.writes[0]['spec']['suspend'])
        self.assertFalse(OBJECTS[0]['spec']['suspend'])

    def test_stage_refuses_existing_cronjob(self):
        k = Kube({('cronjob','k3s-backup'):OBJECTS[0]})
        with patch('lib.apps.render', return_value=copy.deepcopy(OBJECTS)):
            with self.assertRaises(Failure): apps.stage('database-backups', k)
        self.assertEqual(k.writes, [])

    def test_stage_refuses_argo_owner(self):
        k = Kube(owners=[{'spec':{'sources':[{'path':'cluster/infrastructure/backups'}]}}])
        with patch('lib.apps.render', return_value=copy.deepcopy(OBJECTS)):
            with self.assertRaises(Failure): apps.stage('database-backups', k)
        self.assertEqual(k.writes, [])

    def test_dry_run_does_not_create(self):
        k = Kube()
        with patch('lib.apps.render', return_value=copy.deepcopy(OBJECTS)), patch('lib.apps.check', return_value=True):
            apps.stage('database-backups', k, dry_run=True)
        self.assertEqual(k.writes, [])
