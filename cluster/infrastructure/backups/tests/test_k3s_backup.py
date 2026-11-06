import importlib.util, sqlite3, tarfile, tempfile, unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('backup',Path(__file__).resolve().parents[1]/'backup-k3s.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class ExportTests(unittest.TestCase):
 def test_live_wal_export_and_datastore_guard(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);server=root/'server';(server/'db').mkdir(parents=True)
   (server/'token').write_text('synthetic-test-token')
   (server/'node-token').symlink_to('token')
   (server/'agent-token').symlink_to('/var/lib/rancher/k3s/server/token')
   (server/'relative-link').symlink_to('token')
   (server/'tls').mkdir();(server/'tls/test.crt').write_text('synthetic')
   rancher=root/'rancher';(rancher/'k3s').mkdir(parents=True);(rancher/'node').mkdir()
   (rancher/'k3s/config.yaml').write_text('node-name: test');(rancher/'node/password').write_text('synthetic')
   systemd=root/'systemd';systemd.mkdir();(systemd/'k3s.service').write_text('synthetic')
   kubelet=root/'kubelet';kubelet.mkdir()
   conn=sqlite3.connect(server/'db/state.db');conn.execute('pragma journal_mode=wal');conn.execute('create table kine(value)');conn.execute("insert into kine values ('committed')");conn.commit()
   archive=root/'archive.tar.gz';m.export(server,archive,rancher,systemd,kubelet)
   with tarfile.open(archive) as t:
    agent=t.getmember('var/lib/rancher/k3s/server/agent-token')
    self.assertTrue(agent.issym());self.assertEqual(agent.linkname,'/var/lib/rancher/k3s/server/token')
    self.assertEqual(t.getmember('var/lib/rancher/k3s/server/relative-link').linkname,'token')
    names=t.getnames();self.assertFalse(any(n.endswith(('-wal','-shm')) for n in names))
    self.assertEqual(t.extractfile('var/lib/rancher/k3s/server/token').read(),b'synthetic-test-token')
    copied=root/'copy.db';copied.write_bytes(t.extractfile('var/lib/rancher/k3s/server/db/state.db').read())
   with sqlite3.connect(copied) as c:self.assertEqual(c.execute('select value from kine').fetchone()[0],'committed')
   (server/'db/etcd').mkdir()
   with self.assertRaises(RuntimeError):m.export(server,archive,rancher,systemd,kubelet)
   (server/'db/etcd').rmdir();(server/'token').write_text('')
   with self.assertRaises(RuntimeError):m.export(server,archive,rancher,systemd,kubelet)
   conn.close()

if __name__=='__main__':unittest.main()
