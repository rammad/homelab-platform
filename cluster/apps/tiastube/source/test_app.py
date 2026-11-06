import os,tempfile,unittest,sqlite3
from pathlib import Path
import app
class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); app.DB=Path(self.tmp.name)/'test.db'; self.c=app.connect();app.seed(self.c);app.migrate(self.c)
    def tearDown(self): self.c.close();self.tmp.cleanup()
    def test_person_activity_deduplicates_and_keeps_viewers_separate(self):
        did=self.map_laptop()
        self.c.execute('update clients set device_id=? where id=4',(did,))
        self.c.execute("insert into sessions(client,month,minutes) values(1,'2026-09',10)")
        rows={r['person']:r for r in app.person_activity(self.c)}
        self.assertEqual(rows[1]['minutes'],220)
        self.assertEqual(rows[1]['devices'],2)
        self.assertEqual(rows[2]['minutes'],95)
        self.assertEqual(rows[2]['devices'],1)
        self.assertEqual(rows[3]['minutes'],0)
        self.assertEqual(rows[3]['devices'],0)
        self.c.execute('update clients set device_id=null where id=2')
        rows={r['person']:r for r in app.person_activity(self.c)}
        self.assertEqual(rows[1]['unmapped'],1)
        self.assertEqual(rows[1]['minutes'],220)
        self.assertEqual(rows[1]['devices'],2)
        app.approve(self.c,'2026-09',10000)
        self.assertEqual(rows,{r['person']:r for r in app.person_activity(self.c)})

    def test_bills_are_idempotent_and_baseline_separate(self):
        n=self.c.execute('select count(*) from entries').fetchone()[0]
        app.bill(self.c,'2026-10-29');self.assertEqual(n,self.c.execute('select count(*) from entries').fetchone()[0])
        self.assertEqual(32000,self.c.execute("select sum(cents) from entries where kind='baseline'").fetchone()[0])
    def test_mapping_threshold_and_person_scope(self):
        r=app.review(self.c,'2026-09',10);self.assertTrue(r[0]['unresolved']);self.assertEqual(r[1]['devices'],1);self.assertEqual(r[2]['devices'],0)
        self.c.execute("update clients set device_id=(select device_id from clients where id=1) where id=2")
        r=app.review(self.c,'2026-09',10);self.assertFalse(r[0]['unresolved']);self.assertEqual(r[0]['deduction'],400)
        self.assertEqual(app.review(self.c,'2026-09',5)[2]['devices'],1)
    def test_month_end_and_annual_billing(self):
        self.c.execute("insert into subscriptions(name,cents,start,interval,kind) values('Month end',100,'2026-01-31',1,'actual')")
        app.bill(self.c,'2026-03-31'); dates=[r[0] for r in self.c.execute("select date from entries where name='Month end' order by date")]
        self.assertEqual(dates,['2026-01-31','2026-02-28','2026-03-31'])
    def map_laptop(self):
        did=self.c.execute('select device_id from clients where id=1').fetchone()[0]
        self.c.execute('update clients set device_id=? where id=2',(did,))
        return did
    def test_shared_device_charged_once_across_accounts(self):
        did=self.map_laptop()
        self.c.execute('update clients set device_id=? where id=4',(did,))
        rows=app.review(self.c,'2026-09',10)
        self.assertEqual(sum(r['deduction'] for r in rows),400)
        self.assertEqual(next(r for r in rows if r['name']=='Morgan')['deduction'],0)
        app.approve(self.c,'2026-09',10)
        charges=self.c.execute("select * from entries where kind='usage'").fetchall()
        self.assertEqual(len(charges),2)
        self.assertEqual(sum(r['cents'] for r in charges),400)
        with self.assertRaises(ValueError):app.approve(self.c,'2026-09',10)
    def test_pooling_preserves_donor_and_prior_charges(self):
        self.map_laptop();app.approve(self.c,'2026-09',10)
        old=self.c.execute('select details from approvals').fetchone()[0]
        target=app.merge_accounts(self.c,'Family',[1,2])
        self.assertEqual(self.c.execute('select count(*) from people where account_id=?',(target,)).fetchone()[0],2)
        ledger=self.c.execute('select kind,cents,person from entries where account_id=?',(target,)).fetchall()
        self.assertEqual(sum(r['cents'] if r['kind']=='contribution' else -r['cents'] for r in ledger),15400)
        self.assertEqual({r['person'] for r in ledger if r['kind']=='contribution'},{1,2})
        self.assertEqual(self.c.execute('select details from approvals').fetchone()[0],old)
    def test_device_owner_change_does_not_rewrite_approval(self):
        did=self.map_laptop();app.approve(self.c,'2026-09',10)
        self.c.execute('update devices set account_id=2 where id=?',(did,))
        self.assertEqual(self.c.execute('select account_id from entries where source=?',('device:2026-09:'+str(did),)).fetchone()[0],1)
    def test_migration_is_repeatable_and_keeps_mappings(self):
        before=list(self.c.execute('select device_id from clients'))
        app.migrate(self.c)
        self.assertEqual([tuple(x) for x in before],[tuple(x) for x in self.c.execute('select device_id from clients')])
        self.assertEqual(self.c.execute('select count(*) from accounts').fetchone()[0],3)
    def test_reopen_replaces_charges_without_losing_contributions(self):
        self.map_laptop();app.approve(self.c,'2026-09',10)
        app.reopen(self.c,'2026-09')
        self.assertEqual(self.c.execute("select count(*) from entries where kind='usage'").fetchone()[0],0)
        self.assertEqual(self.c.execute('select count(*) from approval_archive').fetchone()[0],1)
        self.assertEqual(self.c.execute("select sum(cents) from entries where kind='contribution'").fetchone()[0],16000)
        app.approve(self.c,'2026-09',10)
        self.assertEqual(self.c.execute("select sum(cents) from entries where kind='usage'").fetchone()[0],600)
    def test_subscription_edits_end_date_and_deletion(self):
        d={'name':'Autopay test','amount':'9.50','start':'2026-06-15','end_date':'2026-08-15','interval':'1','kind':'actual'}
        sid=app.save_subscription(self.c,d)
        def rows():return self.c.execute('select * from entries where source like ? order by date',(f'sub:{sid}:%',)).fetchall()
        self.assertEqual([r['date'] for r in rows()],['2026-06-15','2026-07-15','2026-08-15'])
        app.save_subscription(self.c,{**d,'id':sid,'amount':'12','end_date':'2026-07-14'})
        self.assertEqual([(r['date'],r['cents']) for r in rows()],[('2026-06-15',1200)])
        app.delete_subscription(self.c,sid);app.bill(self.c,'2026-10-29')
        self.assertEqual(len(rows()),0)
    def test_individual_override_and_delete_survive_auto_refresh(self):
        sid=app.save_subscription(self.c,{'name':'Test','amount':'5','start':'2026-06-01','end_date':'2026-07-01','interval':'1','kind':'actual'})
        rows=self.c.execute('select * from entries where source like ? order by date',(f'sub:{sid}:%',)).fetchall()
        app.save_entry(self.c,{'id':rows[0]['id'],'kind':'subscription','name':'Adjusted','amount':'3.25','date':'2026-06-02'})
        app.delete_entry(self.c,rows[1]['id'])
        app.bill(self.c,'2026-10-29');app.bill(self.c,'2026-10-29')
        left=self.c.execute('select * from entries where source like ?',(f'sub:{sid}:%',)).fetchall()
        self.assertEqual(len(left),1);self.assertEqual(left[0]['cents'],325);self.assertEqual(left[0]['date'],'2026-06-02')
    def test_edit_delete_manual_contribution(self):
        row=self.c.execute("select * from entries where kind='contribution' limit 1").fetchone()
        app.save_entry(self.c,{'id':row['id'],'kind':'contribution','name':'Correction','date':'2026-07-01','amount':'42','person':2})
        updated=self.c.execute('select * from entries where id=?',(row['id'],)).fetchone()
        self.assertEqual((updated['cents'],updated['person'],updated['account_id']),(4200,2,2))
        app.delete_entry(self.c,row['id']);self.assertIsNone(self.c.execute('select * from entries where id=?',(row['id'],)).fetchone())
    def test_duplicate_device_merge_reduces_count(self):
        self.map_laptop()
        first=self.c.execute('select device_id from clients where id=1').fetchone()[0]
        duplicate=self.c.execute('select device_id from clients where id=4').fetchone()[0]
        self.assertEqual(sum(r['devices'] for r in app.review(self.c,'2026-09',10)),3)
        app.merge_devices(self.c,duplicate,first)
        self.assertEqual(sum(r['devices'] for r in app.review(self.c,'2026-09',10)),2)
        self.assertEqual(self.c.execute('select device_id from clients where id=4').fetchone()[0],first)
    def test_currency_validation(self):
        self.assertEqual(app.money('12.34'),1234)
        for v in ['nan','-2','1.001','Infinity']:
            with self.assertRaises(ValueError):app.money(v)
if __name__=='__main__':unittest.main()
