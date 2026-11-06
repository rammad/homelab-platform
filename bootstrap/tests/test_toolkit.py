"""Safety tests: no real kubectl calls, host changes or external access."""
import base64
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import apps, argo, host
from lib.common import Failure, confirm, run

OBJECTS = [{'kind': 'Deployment', 'metadata': {'name': 'demo', 'namespace': 'tools'},
            'spec': {'template': {'spec': {'containers': [{'name':'demo', 'env':[
                {'name':'TOKEN', 'valueFrom':{'secretKeyRef':{'name':'demo-auth', 'key':'token'}}}]}]}}}}]

class FakeKube:
    def __init__(self, existing=None):
        self.secret = copy.deepcopy(existing)
        self.calls = []
    def identity(self): return 'test', 'https://test.invalid'
    def get(self, kind, name, namespace=None, sensitive=False):
        if kind == 'namespace': return {'metadata':{'name':name}}
        if kind == 'secret': return copy.deepcopy(self.secret)
        return None
    def call(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        obj = json.loads(kwargs['data']) if kwargs.get('data') else None
        if args[0] == 'create': self.secret = obj
        elif 'patch' in args:
            assert obj[0]['op']=='test' and obj[0]['path']=='/metadata/resourceVersion'
            self.secret['data'] = obj[1]['value']
        return ''

class ToolkitTests(unittest.TestCase):
    def test_secret_discovery_excludes_optional(self):
        objects = copy.deepcopy(OBJECTS)
        env = objects[0]['spec']['template']['spec']['containers'][0]['env']
        env.append({'valueFrom':{'secretKeyRef':{'name':'optional','key':'x','optional':True}}})
        self.assertEqual(apps.secret_refs(objects), {('tools','demo-auth'):{'token'}})

    @patch('lib.apps.render', return_value=OBJECTS)
    def test_existing_secret_default_is_noop(self, _):
        k=FakeKube({'metadata':{'resourceVersion':'1'},'data':{'token':'eA=='}})
        with patch('lib.apps.hidden', side_effect=AssertionError('must not prompt')):
            apps.configure_secrets('demo', k)
        self.assertEqual(k.calls, [])

    @patch('lib.apps.render', return_value=OBJECTS)
    def test_secret_dry_run_does_not_prompt_or_write(self, _):
        k=FakeKube()
        with patch('lib.apps.hidden', side_effect=AssertionError('must not prompt')):
            apps.configure_secrets('demo', k, dry_run=True)
        self.assertEqual(k.calls, [])

    @patch('lib.apps.render', return_value=OBJECTS)
    @patch('lib.apps.confirm', return_value=True)
    @patch('lib.apps.hidden', return_value='new-value')
    def test_secret_update_preserves_other_keys_and_uses_stdin(self, *_):
        k=FakeKube({'metadata':{'resourceVersion':'7'},'data':{'token':'b2xk','unrelated':'a2VlcA=='}})
        apps.configure_secrets('demo', k, replace=True)
        self.assertEqual(k.secret['data']['unrelated'], 'a2VlcA==')
        self.assertEqual(k.secret['data']['token'], base64.b64encode(b'new-value').decode())
        args, kwargs = k.calls[0]
        self.assertIn('--patch-file=/dev/stdin',args)
        self.assertNotIn('new-value',str(args))
        self.assertTrue(kwargs['sensitive'])

    @patch('lib.apps.render', return_value=OBJECTS)
    @patch('lib.apps.confirm', return_value=True)
    @patch('lib.apps.hidden', side_effect=['one','two'])
    def test_mismatch_does_not_write(self, *_):
        k=FakeKube()
        with self.assertRaises(Failure): apps.configure_secrets('demo', k)
        self.assertFalse(k.calls)

    @patch('lib.apps.render', return_value=OBJECTS)
    def test_controller_secret_refused(self, _):
        k=FakeKube({'metadata':{'ownerReferences':[{'name':'controller'}]},'data':{}})
        with self.assertRaises(Failure): apps.configure_secrets('demo', k, replace=True)
        self.assertFalse(k.calls)

    @patch('lib.host.require_debian_root')
    @patch('lib.host.installed', return_value=True)
    @patch('lib.host.run', side_effect=AssertionError('must not run installer'))
    def test_existing_k3s_refuses_install(self, *_):
        with self.assertRaisesRegex(Failure, 'Refusing reinstall'):
            host.fresh_install('control-plane', 'test')

    def test_sensitive_errors_redacted(self):
        with self.assertRaises(Failure) as e:
            run([sys.executable,'-c','import sys;sys.stderr.write("secret-value");sys.exit(1)'],sensitive=True)
        self.assertNotIn('secret-value',str(e.exception))

    def test_manifest_catalog_and_refs(self):
        for name in apps.names():
            obj, recorded = apps.application(name)
            self.assertEqual(obj['spec']['source']['path'], str(apps.source(name).relative_to(apps.ROOT)))
            self.assertTrue((apps.ROOT/obj['spec']['source']['path']).is_dir())
        refs=apps.secret_refs(apps.documents('nextcloud'))
        self.assertEqual(refs[('data','nextcloud-cache-auth')],{'password'})
        # No TLS secret should be presented for manual generation.
        self.assertNotIn(('data','nextcloud-tls'),refs)

    @patch('lib.apps.check', return_value=True)
    def test_register_existing_is_noop(self, _):
        obj, _=apps.application('nextcloud')
        k=FakeKube()
        k.get=lambda *a,**kw: obj
        apps.register('nextcloud',k)
        self.assertFalse(k.calls)

    @patch('lib.apps.check', return_value=True)
    def test_register_duplicate_source_refused(self, _):
        obj,_=apps.application('nextcloud')
        obj['metadata']['name']='other-owner'
        k=FakeKube()
        k.call=lambda *a,**kw: json.dumps({'items':[obj]})
        with self.assertRaisesRegex(Failure,'Another Application'):
            apps.register('nextcloud',k)

    @patch('lib.apps.render', return_value=[{'kind':'PersistentVolume','metadata':{'name':'test'},'spec':{'nfs':{'server':'nas','path':'/expected'}}}])
    def test_storage_path_conflict_refused(self, _):
        k=FakeKube()
        k.get=lambda *a,**kw: {'spec':{'nfs':{'server':'nas','path':'/wrong'}}}
        with self.assertRaisesRegex(Failure,'differs in nfs'): apps.prepare_storage('nextcloud',k)
        self.assertFalse(k.calls)

    def test_argo_existing_refuses_install(self):
        k=FakeKube(); k.get=lambda *a,**kw:{'metadata':{'name':'argocd-server'}}
        with self.assertRaisesRegex(Failure,'already exists'): argo.install(k)
        self.assertFalse(k.calls)

class AdditionalSafetyTests(unittest.TestCase):
    @patch('lib.host.require_debian_root')
    @patch('lib.host.installed', return_value=False)
    @patch('lib.host.run', side_effect=AssertionError('no host commands allowed'))
    def test_bad_node_name_rejected_before_install(self, *_):
        with self.assertRaisesRegex(Failure, 'hostname'):
            host.fresh_install('worker', 'bad;command', 'https://server:6443')

    @patch('lib.apps.render', return_value=OBJECTS)
    @patch('lib.apps.confirm', return_value=True)
    @patch('lib.apps.hidden', return_value='new-secret')
    def test_new_secret_uses_create_stdin(self, *_):
        k=FakeKube()
        apps.configure_secrets('demo', k)
        args, kwargs=k.calls[0]
        self.assertEqual(args, ('create','-f','-'))
        self.assertTrue(kwargs['sensitive'])
        self.assertEqual(k.secret['metadata']['namespace'],'tools')

    @patch('lib.apps.render', return_value=OBJECTS)
    def test_immutable_secret_refused(self, _):
        k=FakeKube({'metadata':{},'immutable':True,'data':{}})
        with self.assertRaisesRegex(Failure, 'immutable'):
            apps.configure_secrets('demo',k)
        self.assertFalse(k.calls)

    @patch('lib.apps.render', return_value=[{'kind':'Deployment','metadata':{'name':'emby','namespace':'media'},'spec':{'template':{'spec':{'volumes':[{'persistentVolumeClaim':{'claimName':'arr-media'}}]}}}}])
    def test_shared_claim_missing_is_reported(self, _):
        k=FakeKube()
        self.assertFalse(apps.check('emby',k))
        self.assertFalse(k.calls)

    @patch('lib.apps.render', return_value=[{'kind':'PersistentVolume','metadata':{'name':'demo'},'spec':{'nfs':{'server':'nas','path':'/data'}}}])
    def test_storage_dry_run_never_creates(self, _):
        k=FakeKube()
        apps.prepare_storage('nextcloud',k,dry_run=True)
        self.assertFalse(k.calls)

if __name__=='__main__': unittest.main()
