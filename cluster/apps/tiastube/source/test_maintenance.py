import contextlib,copy,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import app,maintenance as m

class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();app.DB=Path(self.tmp.name)/'test.sqlite3'
        with app.connect() as c:app.seed(c);app.migrate(c)
        self.users=[{'id':'u1','username':'Viewer'}]
        self.play={'id':'s1','serverId':'server','user':self.users[0], 'startedAt':'2026-09-04T20:00:00Z','durationMs':1200000,'device':'Shield','player':'Emby','product':'Emby','platform':'Android'}
    def tearDown(self):self.tmp.cleanup()
    def test_idempotent_sync_preserves_mapping_and_money(self):
        with app.connect() as c:
            m.ingest(c,self.users,[self.play]);before=c.execute('select count(*) from entries').fetchone()[0]
            cid=c.execute('select client from external_clients').fetchone()[0]
            c.execute('update clients set device_id=1 where id=?',(cid,))
            result=m.ingest(c,self.users,[self.play]);self.assertEqual(result['added'],0)
            self.assertEqual(c.execute('select device_id from clients where id=?',(cid,)).fetchone()[0],1)
            self.assertEqual(c.execute('select count(*) from entries').fetchone()[0],before)
    def test_changed_approved_usage_flagged_without_changing_charges(self):
        with app.connect() as c:
            m.ingest(c,self.users,[self.play]);c.execute("insert into approvals values('2026-09',10,200,'[]')")
            changed={**self.play,'durationMs':2400000};m.ingest(c,self.users,[changed])
            self.assertEqual(m.metadata(c,'sync_changed_approvals'),['2026-09'])
            self.assertEqual(c.execute("select details from approvals").fetchone()[0],'[]')
    def test_invalid_record_rolls_back_whole_import(self):
        with self.assertRaises(ValueError),app.connect() as c:
            m.ingest(c,self.users,[self.play,{**self.play,'id':'bad','durationMs':'invalid'}])
        with app.connect() as c:self.assertEqual(c.execute("select count(*) from people where name='Viewer'").fetchone()[0],0)
    def test_backup_restore_round_trip_and_safety_copy(self):
        name=m.backup(app.DB)
        with app.connect() as c:c.execute("update people set name='Changed' where id=1")
        safety=m.restore(app.DB,name)
        with app.connect() as c:self.assertEqual(c.execute('select name from people where id=1').fetchone()[0],'Alex')
        with contextlib.closing(sqlite3.connect(m.backup_path(app.DB,safety))) as c:self.assertEqual(c.execute('select name from people where id=1').fetchone()[0],'Changed')
    def test_reject_bad_backup_and_paths(self):
        with self.assertRaises(ValueError):m.backup_path(app.DB,'../test.sqlite3')
        name=m.backup(app.DB);p=m.backup_path(app.DB,name)
        with contextlib.closing(sqlite3.connect(p)) as c:c.execute('drop table people');c.commit()
        with self.assertRaises(ValueError):m.restore(app.DB,name)
        with app.connect() as c:self.assertEqual(c.execute('select count(*) from people').fetchone()[0],3)
    def test_restore_refused_during_sync(self):
        name=m.backup(app.DB);m.JOB.acquire()
        try:
            with self.assertRaises(ValueError):m.restore(app.DB,name)
        finally:m.JOB.release()
    def test_pagination_detects_duplicates_and_changing_total(self):
        def duplicate(cfg,resource,params):return {'data':[{'id':'same'}],'meta':{'total':2}}
        with patch.object(m.time,'sleep'),self.assertRaises(ValueError):m.pages({},'history',fetch=duplicate)
        def changed(cfg,resource,params):return {'data':[{'id':str(params['page'])}],'meta':{'total':params['page']+1}}
        with patch.object(m.time,'sleep'),self.assertRaises(ValueError):m.pages({},'history',fetch=changed)
    def test_duplicate_boundary_restarts_without_retaining_partial_rows(self):
        calls=[]
        def fetch(cfg,resource,params):
            calls.append((params['pageSize'],params['page']))
            if params['pageSize']==100:
                rows=[{'id':'discarded'}] if params['page']==1 else [{'id':'discarded'}]
            else:
                rows=[{'id':'a'},{'id':'b'}]
            return {'data':rows,'meta':{'total':2}}
        with patch.object(m.time,'sleep'):
            rows=m.pages({},'history',fetch=fetch)
        self.assertEqual([r['id'] for r in rows],['a','b'])
        self.assertIn((99,1),calls)
        self.assertEqual(calls[:2],[(100,1),(100,2)])

    def test_overlapping_boundary_recovers_missing_id_before_accepting(self):
        def fetch(cfg,resource,params):
            if params['pageSize']==100:
                rows=[{'id':'a'},{'id':'b'}] if params['page']==1 else [{'id':'b'},{'id':'d'}]
            else:
                rows=[{'id':'a'},{'id':'b'},{'id':'c'},{'id':'d'}]
            return {'data':rows,'meta':{'total':4}}
        with patch.object(m.time,'sleep'):
            rows=m.pages({},'history',fetch=fetch)
        self.assertEqual({r['id'] for r in rows},{'a','b','c','d'})

    def test_changed_total_retries_from_first_page(self):
        def fetch(cfg,resource,params):
            if params['pageSize']==100:
                return {'data':[{'id':str(params['page'])}], 'meta':{'total':2 if params['page']==1 else 3}}
            return {'data':[{'id':'a'}], 'meta':{'total':1}}
        with patch.object(m.time,'sleep'):
            self.assertEqual(m.pages({},'history',fetch=fetch),[{'id':'a'}])

    def test_persistent_duplicate_is_bounded_and_reports_resource(self):
        calls=[]
        def fetch(cfg,resource,params):
            calls.append(params)
            return {'data':[{'id':'a'},{'id':'a'}], 'meta':{'total':2}}
        with patch.object(m.time,'sleep'),self.assertRaisesRegex(ValueError,'history page 1'):
            m.pages({},'history',fetch=fetch)
        self.assertLessEqual(len(calls),9)

    def test_malformed_record_is_not_treated_as_transient_pagination(self):
        fetch=unittest.mock.Mock(return_value={'data':[{'username':'missing ID'}],'meta':{'total':1}})
        with self.assertRaisesRegex(ValueError,'Invalid Tracearr record ID at users page 1'):
            m.pages({},'users',fetch=fetch)
        self.assertEqual(fetch.call_count,1)

    def test_failed_sync_keeps_watermark_and_records(self):
        with app.connect() as c:m.put(c,'sync_status',{'last_success':'2026-09-01T00:00:00+00:00'})
        def fail(*args):raise ValueError('Simulated API failure')
        with patch.object(m,'config',return_value={'url':'http://example.test','key':'fake'}):
            m.JOB.acquire();m.run_sync(app,fetch=fail)
        with app.connect() as c:
            state=m.metadata(c,'sync_status');self.assertEqual(state['last_success'],'2026-09-01T00:00:00+00:00');self.assertEqual(state['error'],'Simulated API failure')
    def test_incremental_catches_up_from_last_success(self):
        previous={'last_success':'2026-10-28T00:00:00+00:00','last_full':m.now()}
        with app.connect() as c:m.put(c,'sync_status',previous)
        calls=[]
        def fetch(cfg,resource,params):
            calls.append((resource,params));return {'data':self.users if resource=='users' else [self.play],'meta':{'total':1}}
        with patch.object(m,'config',return_value={'url':'http://example.test','key':'fake'}):
            m.JOB.acquire();m.run_sync(app,fetch=fetch)
        self.assertEqual(calls[1][1]['startDate'],'2026-09-13T00:00:00+00:00')
        with app.connect() as c:self.assertIsNone(m.metadata(c,'sync_status')['error'])
    def test_upload_and_restore_downloaded_backup(self):
        original=m.backup(app.DB)
        content=m.backup_path(app.DB,original).read_bytes()
        uploaded=m.upload(app.DB,content)
        with app.connect() as c:c.execute("delete from entries")
        m.restore(app.DB,uploaded)
        with app.connect() as c:self.assertGreater(c.execute('select count(*) from entries').fetchone()[0],0)
        with self.assertRaises(ValueError):m.upload(app.DB,b'not a database')

    def test_daily_retention_does_not_remove_manual(self):
        manual=m.backup(app.DB)
        for _ in range(32):m.backup(app.DB,'daily')
        self.assertTrue(m.backup_path(app.DB,manual).exists())
        self.assertEqual(len(list((m.directory(app.DB)/'backups').glob('*-daily-*'))),30)

if __name__=='__main__':unittest.main()
