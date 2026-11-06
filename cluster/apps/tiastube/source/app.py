import calendar, datetime as dt, json, os, sqlite3, sys, threading, signal, fcntl
import maintenance
from decimal import Decimal, InvalidOperation
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).parent
DB=Path(os.environ.get('TIASTUBE_DB', ROOT/'demo.sqlite3'))
BIND=os.environ.get('TIASTUBE_BIND','127.0.0.1')
PORT=int(os.environ.get('TIASTUBE_HTTP_PORT','8765'))
PRODUCTION=os.environ.get('TIASTUBE_MODE')=='production'
ALLOWED_HOSTS=set(os.environ.get('TIASTUBE_ALLOWED_HOSTS','127.0.0.1:8765,localhost:8765').split(','))
ALLOWED_ORIGINS=set(os.environ.get('TIASTUBE_ALLOWED_ORIGINS','http://127.0.0.1:8765,http://localhost:8765').split(','))
class Connection(sqlite3.Connection):
    def __exit__(self,*args):
        try:return super().__exit__(*args)
        finally:self.close()
def connect():
    c=sqlite3.connect(DB,timeout=30,factory=Connection); c.row_factory=sqlite3.Row
    c.execute('pragma synchronous=FULL');return c
def money(v):
    try:
        d=Decimal(str(v))
        if not d.is_finite() or d<=0 or d>1000000 or d.as_tuple().exponent < -2: raise ValueError('Use a positive amount with at most two decimals.')
        return int(d*100)
    except InvalidOperation: raise ValueError('Invalid amount')
def required(v):
    v=str(v).strip()
    if not v or len(v)>120: raise ValueError('Enter a name of 1–120 characters.')
    return v
def seed(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS people(id INTEGER PRIMARY KEY,name TEXT);
CREATE TABLE IF NOT EXISTS entries(id INTEGER PRIMARY KEY,kind TEXT,name TEXT,person INTEGER,date TEXT,cents INTEGER,source TEXT UNIQUE,override INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS subscriptions(id INTEGER PRIMARY KEY,name TEXT,cents INTEGER,start TEXT,interval INTEGER,kind TEXT,active INTEGER DEFAULT 1,end_date TEXT,deleted INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY,person INTEGER,name TEXT,device TEXT);
CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY,client INTEGER,month TEXT,minutes INTEGER);
CREATE TABLE IF NOT EXISTS approvals(month TEXT PRIMARY KEY,threshold INTEGER,rate INTEGER,details TEXT);
CREATE TABLE IF NOT EXISTS entry_skips(source TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS change_archive(id INTEGER PRIMARY KEY,changed_at TEXT,kind TEXT,data TEXT);
''')
    if PRODUCTION or c.execute('select count(*) from people').fetchone()[0]: return
    c.executemany('insert into people(id,name) values (?,?)',[(1,'Alex'),(2,'Morgan'),(3,'Sam')])
    c.executemany('insert into entries(kind,name,person,date,cents,source) values(?,?,?,?,?,?)',[
        ('purchase','Starter server',None,'2026-06-05',25000,'seed1'),('purchase','Storage drive',None,'2026-08-12',9000,'seed2'),('contribution','Contribution',1,'2026-06-10',10000,'seed3'),('contribution','Contribution',2,'2026-07-01',6000,'seed4'),('refund','Drive rebate',None,'2026-08-20',1000,'seed5')])
    c.executemany('insert into subscriptions(name,cents,start,interval,kind) values(?,?,?,?,?)', [('Emby demo',500,'2026-06-01',1,'actual'),('Usenet demo',800,'2026-06-01',1,'actual'),('Streaming alternative',6400,'2026-06-01',1,'baseline')])
    c.executemany('insert into clients(id,person,name,device) values(?,?,?,?)',[(1,1,'Chrome / Windows','Laptop'),(2,1,'Emby desktop',''),(3,1,'Living-room TV','TV'),(4,2,'Android phone','Phone'),(5,2,'Firefox / Linux',''),(6,3,'Tablet','Tablet')])
    c.executemany('insert into sessions(client,month,minutes) values(?,?,?)',[(1,'2026-09',65),(2,'2026-09',110),(3,'2026-09',45),(4,'2026-09',95),(5,'2026-09',7),(6,'2026-09',10)])
    bill(c,'2026-10-29')
def bill(c,through):
    end=dt.date.fromisoformat(through)
    if end>dt.datetime.now(ZoneInfo('America/Los_Angeles')).date(): raise ValueError('Cannot post future costs.')
    count=0
    for s in c.execute('select * from subscriptions where active=1 and deleted=0').fetchall():
        start=dt.date.fromisoformat(s['start']); offset=0; sources=set()
        stop=min(end,dt.date.fromisoformat(s['end_date'])) if s['end_date'] else end
        while True:
            y=start.year+(start.month-1+offset)//12; m=(start.month-1+offset)%12+1
            date=dt.date(y,m,min(start.day,calendar.monthrange(y,m)[1]))
            if date>stop:break
            source=f"sub:{s['id']}:{date}";sources.add(source)
            if not c.execute('select 1 from entry_skips where source=?',(source,)).fetchone():
                kind='baseline' if s['kind']=='baseline' else 'subscription'
                count+=c.execute("""insert into entries(kind,name,date,cents,source) values(?,?,?,?,?)
                    on conflict(source) do update set kind=excluded.kind,name=excluded.name,date=excluded.date,cents=excluded.cents
                    where entries.override=0""",(kind,s['name'],date.isoformat(),s['cents'],source)).rowcount
            offset+=s['interval']
        for row in c.execute('select id,source from entries where source like ?',(f"sub:{s['id']}:%",)).fetchall():
            if row['source'] not in sources:c.execute('delete from entries where id=?',(row['id'],))
    return count

def archive(c,kind,data):
    c.execute('insert into change_archive(changed_at,kind,data) values(?,?,?)',(dt.datetime.now(dt.timezone.utc).isoformat(),kind,json.dumps(data)))
def save_subscription(c,d):
    interval=int(d['interval']);kind=d['kind'];start=dt.date.fromisoformat(d['start']).isoformat()
    end=dt.date.fromisoformat(d['end_date']).isoformat() if d.get('end_date') else None
    if interval not in (1,12) or kind not in ('actual','baseline'):raise ValueError('Invalid subscription')
    if end and end<start:raise ValueError('End date must be on or after the start date.')
    values=(required(d['name']),money(d['amount']),start,interval,kind,end)
    if d.get('id'):
        ident=require_id(c,'subscriptions',d['id']);old=dict(c.execute('select * from subscriptions where id=?',(ident,)).fetchone())
        if old['deleted']:raise ValueError('Subscription has been deleted.')
        archive(c,'subscription edit',old)
        c.execute('update subscriptions set name=?,cents=?,start=?,interval=?,kind=?,end_date=?,active=1 where id=?',(*values,ident))
    else:ident=c.execute('insert into subscriptions(name,cents,start,interval,kind,end_date) values(?,?,?,?,?,?)',values).lastrowid
    bill(c,dt.datetime.now(ZoneInfo('America/Los_Angeles')).date().isoformat())
    return ident

def delete_subscription(c,ident):
    ident=require_id(c,'subscriptions',ident)
    archive(c,'subscription delete',{'schedule':dict(c.execute('select * from subscriptions where id=?',(ident,)).fetchone()),'entries':[dict(r) for r in c.execute('select * from entries where source like ?',(f'sub:{ident}:%',))]})
    c.execute('update subscriptions set deleted=1,active=0 where id=?',(ident,))
    c.execute('delete from entries where source like ?',(f'sub:{ident}:%',))

def save_entry(c,d):
    old=None
    if d.get('id'):
        ident=require_id(c,'entries',d['id']);old=dict(c.execute('select * from entries where id=?',(ident,)).fetchone())
        if old['kind']=='usage':raise ValueError('Reopen the usage month to change its device deductions.')
    kind=d['kind']
    allowed=['purchase','contribution','refund'] if not old or old['kind'] not in ('subscription','baseline') else [old['kind']]
    if kind not in allowed:raise ValueError('Invalid transaction type')
    person=require_id(c,'people',d['person']) if kind=='contribution' else None
    account=c.execute('select account_id from people where id=?',(person,)).fetchone()[0] if person else None
    values=(kind,required(d['name']),person,dt.date.fromisoformat(d['date']).isoformat(),money(d['amount']),account)
    if old:
        archive(c,'entry edit',old)
        c.execute('update entries set kind=?,name=?,person=?,date=?,cents=?,account_id=?,override=1 where id=?',(*values,ident))
    else:c.execute('insert into entries(kind,name,person,date,cents,account_id) values(?,?,?,?,?,?)',values)

def delete_entry(c,ident):
    ident=require_id(c,'entries',ident);row=dict(c.execute('select * from entries where id=?',(ident,)).fetchone())
    if row['kind']=='usage':raise ValueError('Reopen the usage month to remove its deductions.')
    archive(c,'entry delete',row)
    if row['source'] and row['source'].startswith('sub:'):c.execute('insert or ignore into entry_skips values(?)',(row['source'],))
    c.execute('delete from entries where id=?',(ident,))

def merge_devices(c,source,target):
    source=require_id(c,'devices',source);target=require_id(c,'devices',target)
    if source==target:raise ValueError('Select two different devices.')
    src=dict(c.execute('select * from devices where id=?',(source,)).fetchone());dst=dict(c.execute('select * from devices where id=?',(target,)).fetchone())
    archive(c,'device merge',{'source':src,'target':dst,'clients':[dict(r) for r in c.execute('select * from clients where device_id=?',(source,))]})
    c.execute('update clients set device_id=?,device=? where device_id=?',(target,dst['name'],source))
    c.execute('delete from devices where id=?',(source,))
    # Approved snapshots remain frozen; users can explicitly reopen them.
    return target

def migrate(c):
    c.executescript("""CREATE TABLE IF NOT EXISTS accounts(id INTEGER PRIMARY KEY,name TEXT);
CREATE TABLE IF NOT EXISTS devices(id INTEGER PRIMARY KEY,name TEXT,account_id INTEGER);
CREATE TABLE IF NOT EXISTS app_meta(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS approval_archive(id INTEGER PRIMARY KEY,month TEXT,archived_at TEXT,approval TEXT,entries TEXT);""")
    for table,col in [('people','account_id'),('entries','account_id'),('clients','device_id')]:
        if col not in [r[1] for r in c.execute('pragma table_info('+table+')')]: c.execute('alter table '+table+' add column '+col+' INTEGER')
    for table,col,kind in [('entries','override','INTEGER DEFAULT 0'),('subscriptions','end_date','TEXT'),('subscriptions','deleted','INTEGER DEFAULT 0')]:
        if col not in [r[1] for r in c.execute('pragma table_info('+table+')')]:c.execute('alter table '+table+' add column '+col+' '+kind)
    for person in c.execute('select * from people where account_id is null').fetchall():
        aid=c.execute('insert into accounts(name) values(?)',(person['name'],)).lastrowid
        c.execute('update people set account_id=? where id=?',(aid,person['id']))
    c.execute("update entries set account_id=(select account_id from people where people.id=entries.person) where account_id is null and person is not null")
    if not c.execute("select 1 from app_meta where key='device_migration'").fetchone():
        # Preserve existing mappings within each person; do not guess cross-person identity.
        mapped={}
        for cl in c.execute('select clients.*,people.account_id from clients join people on people.id=clients.person').fetchall():
            if not cl['device'].strip(): continue
            key=(cl['person'],cl['device'].strip().casefold())
            if key not in mapped: mapped[key]=c.execute('insert into devices(name,account_id) values(?,?)',(cl['device'].strip(),cl['account_id'])).lastrowid
            c.execute('update clients set device_id=? where id=?',(mapped[key],cl['id']))
        c.execute("insert into app_meta values('device_migration','1')")
def require_id(c,table,ident):
    ident=int(ident)
    if not c.execute('select 1 from '+table+' where id=?',(ident,)).fetchone(): raise ValueError('Unknown '+table+' record')
    return ident
def merge_accounts(c,name,ids):
    ids=list(set(require_id(c,'accounts',i) for i in ids))
    if len(ids)<2: raise ValueError('Select at least two accounts to pool.')
    target=c.execute('insert into accounts(name) values(?)',(required(name),)).lastrowid
    for ident in ids:
        for table in ['people','entries','devices']:c.execute('update '+table+' set account_id=? where account_id=?',(target,ident))
        c.execute('delete from accounts where id=?',(ident,))
    return target

def person_activity(c):
    """Viewing statistics use a fixed 10-minute floor, independent of billing waivers."""
    return [dict(r) for r in c.execute("""select cl.person,s.month,
        sum(case when s.minutes>10 then s.minutes else 0 end) minutes,
        count(distinct case when s.minutes>10 then cl.device_id end) devices,
        count(distinct case when s.minutes>10 and cl.device_id is null then cl.id end) unmapped
        from sessions s join clients cl on cl.id=s.client
        group by cl.person,s.month order by cl.person,s.month""")]

def review(c,month,threshold):
    result={r['id']:{**dict(r),'clients':[],'charged_devices':[],'devices':0,'unresolved':False,'deduction':0} for r in c.execute('select * from accounts order by name')}
    qualifying=set()
    for r in c.execute("""select cl.*,p.name person_name,p.account_id viewer_account,d.name device_name,d.account_id device_account,
        sum(s.minutes) minutes,sum(case when s.minutes>? then s.minutes else 0 end) eligible,
        sum(case when s.minutes<=? then s.minutes else 0 end) ignored
        from clients cl join people p on p.id=cl.person join sessions s on s.client=cl.id
        left join devices d on d.id=cl.device_id where s.month=? group by cl.id""",(threshold,threshold,month)):
        r=dict(r);r['device']=r['device_name'] or '';result[r['viewer_account']]['clients'].append(r)
        if r['eligible']:
            if not r['device_id'] or r['device_account'] not in result: result[r['viewer_account']]['unresolved']=True
            else: qualifying.add(r['device_id'])
    for did in sorted(qualifying):
        device=dict(c.execute('select * from devices where id=?',(did,)).fetchone())
        row=result[device['account_id']];row['charged_devices'].append(device);row['devices']+=1;row['deduction']+=200
    return list(result.values())

def approve(c,month,threshold):
    if month>=dt.datetime.now(ZoneInfo('America/Los_Angeles')).strftime('%Y-%m'):raise ValueError('Only completed months can be approved.')
    if c.execute('select 1 from approvals where month=?',(month,)).fetchone(): raise ValueError('Month already approved.')
    rows=review(c,month,threshold)
    if any(r['unresolved'] for r in rows):raise ValueError('Map qualifying clients to physical devices before approving.')
    c.execute('insert into approvals values(?,?,?,?)',(month,threshold,200,json.dumps(rows)))
    date=month+'-'+str(calendar.monthrange(int(month[:4]),int(month[5:]))[1])
    for row in rows:
        for device in row['charged_devices']:
            c.execute('insert into entries(kind,name,date,cents,source,account_id) values(?,?,?,?,?,?)',('usage',month+' · '+device['name'],date,200,f"device:{month}:{device['id']}",row['id']))
def reopen(c,month):
    approval=c.execute('select * from approvals where month=?',(month,)).fetchone()
    if not approval:raise ValueError('Month is not approved.')
    entries=c.execute("select * from entries where kind='usage' and (source like ? or source like ?)",('usage:'+month+':%','device:'+month+':%')).fetchall()
    c.execute('insert into approval_archive(month,archived_at,approval,entries) values(?,?,?,?)',(month,dt.datetime.now(dt.timezone.utc).isoformat(),json.dumps(dict(approval)),json.dumps([dict(e) for e in entries])))
    for entry in entries:c.execute('delete from entries where id=?',(entry['id'],))
    c.execute('delete from approvals where month=?',(month,))
    maintenance.put(c,'sync_changed_approvals',[m for m in maintenance.metadata(c,'sync_changed_approvals',[]) if m!=month])

class Handler(BaseHTTPRequestHandler):
    def send(self,data,status=200):
        b=json.dumps(data).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(b)
    @maintenance.serialized
    def do_GET(self):
        if self.path=='/healthz':
            self.send({'ok':True});return
        if self.headers.get('Host') not in ALLOWED_HOSTS: self.send({'error':'Invalid host'},403); return
        if self.path=='/api/maintenance':self.send(maintenance.status(sys.modules[__name__]));return
        if self.path.startswith('/api/backup/download?'):
            try:
                name=maintenance.urllib.parse.parse_qs(maintenance.urllib.parse.urlsplit(self.path).query).get('name',[''])[0]
                p=maintenance.backup_path(DB,name)
                self.send_response(200);self.send_header('Content-Type','application/vnd.sqlite3');self.send_header('Content-Disposition','attachment; filename="'+p.name+'"');self.send_header('Content-Length',str(p.stat().st_size));self.end_headers()
                with p.open('rb') as f:
                    while chunk:=f.read(65536):self.wfile.write(chunk)
            except ValueError as e:self.send({'error':str(e)},400)
            return
        if self.path=='/api/state':
            with connect() as c:
                bill(c,dt.datetime.now(ZoneInfo('America/Los_Angeles')).date().isoformat())
                data={t:[dict(x) for x in c.execute('select * from '+t)] for t in ['people','entries','subscriptions','clients','approvals','accounts','devices']}
                data['subscriptions']=[s for s in data['subscriptions'] if not s['deleted']]
                data['today']=dt.datetime.now(ZoneInfo('America/Los_Angeles')).date().isoformat()
                data['months']=[r[0] for r in c.execute('select distinct month from sessions order by month desc')]
                data['live']=PRODUCTION or DB.name=='tracearr.sqlite3'
                data['review']=[]
                data['person_activity']=person_activity(c)
            self.send(data); return
        files={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}
        if self.path not in files: self.send({'error':'Not found'},404); return
        p=ROOT/'static'/files[self.path]; self.send_response(200); self.send_header('Content-Type',{'html':'text/html','js':'text/javascript','css':'text/css'}[p.suffix[1:]]); self.end_headers(); self.wfile.write(p.read_bytes())
    @maintenance.serialized
    def do_POST(self):
        if self.headers.get('Host') not in ALLOWED_HOSTS or self.headers.get('Origin') not in (None,*ALLOWED_ORIGINS):self.send({'error':'Invalid request origin'},403);return
        if self.path=='/api/backup/upload':
            try:
                length=int(self.headers.get('Content-Length',0))
                if length<=0 or length>64*1024*1024:raise ValueError('Backup must be no larger than 64 MB.')
                self.send({'name':maintenance.upload(DB,self.rfile.read(length))})
            except ValueError as e:self.send({'error':str(e)},400)
            return
        if self.headers.get('Content-Type')!='application/json':self.send({'error':'Invalid request type'},403);return
        try:
            d=json.loads(self.rfile.read(min(int(self.headers.get('Content-Length',0)),20000)))
            if self.path=='/api/tracearr/config':maintenance.configure(DB,d);self.send({'ok':True});return
            if self.path=='/api/tracearr/sync':maintenance.start_sync(sys.modules[__name__],bool(d.get('full')));self.send({'ok':True});return
            if self.path=='/api/backup/create':self.send({'name':maintenance.backup(DB)});return
            if self.path=='/api/backup/restore':self.send({'safety_backup':maintenance.restore(DB,d['name'])});return
            with connect() as c:
                action=self.path
                if action=='/api/entry':save_entry(c,d)
                elif action=='/api/entry_delete':delete_entry(c,d['id'])
                elif action=='/api/subscription':save_subscription(c,d)
                elif action=='/api/subscription_delete':delete_subscription(c,d['id'])
                elif action=='/api/device_merge':merge_devices(c,d['source'],d['target'])
                elif action=='/api/person':
                    name=required(d['name']); aid=c.execute('insert into accounts(name) values(?)',(name,)).lastrowid
                    c.execute('insert into people(name,account_id) values(?,?)',(name,aid))
                elif action=='/api/reopen':
                    month=d['month'];dt.date.fromisoformat(month+'-01');reopen(c,month)
                elif action=='/api/group': merge_accounts(c,d['name'],d['accounts'])
                elif action=='/api/device':
                    aid=require_id(c,'accounts',d['account_id']); name=required(d['name'])
                    if d.get('id'):
                        did=require_id(c,'devices',d['id']);c.execute('update devices set name=?,account_id=? where id=?',(name,aid,did))
                        c.execute('update clients set device=? where device_id=?',(name,did))
                    else:c.execute('insert into devices(name,account_id) values(?,?)',(name,aid))
                elif action=='/api/mapping':
                    cid=require_id(c,'clients',d['id']);did=require_id(c,'devices',d['device_id']) if d.get('device_id') else None
                    name=c.execute('select name from devices where id=?',(did,)).fetchone()[0] if did else ''
                    c.execute('update clients set device=?,device_id=? where id=?',(name,did,cid))
                elif action in ('/api/review','/api/approve'):
                    month=d.get('month','2026-09'); dt.date.fromisoformat(month+'-01'); threshold=int(d['threshold'])
                    if threshold<0 or threshold>10000: raise ValueError('Threshold must be 0–10,000 minutes')
                    rows=review(c,month,threshold)
                    if action=='/api/review': self.send(rows); return
                    approve(c,month,threshold)
                elif action=='/api/reset':
                    if PRODUCTION or DB.name=='tracearr.sqlite3': raise ValueError('Reset is disabled for imported data.')
                    for t in ['entries','subscriptions','clients','sessions','approvals','people','devices','accounts','app_meta','entry_skips','change_archive','approval_archive']: c.execute('delete from '+t)
                    seed(c); migrate(c)
                else: raise ValueError('Unknown action')
            self.send({'ok':True})
        except (OSError,sqlite3.DatabaseError) as e: self.send({'error':'Database operation failed; check server storage and backup integrity.'},400)
        except (ValueError,KeyError) as e: self.send({'error':'This record conflicts with an existing entry.' if isinstance(e,sqlite3.IntegrityError) else str(e)},400)
if __name__=='__main__':
    DB.parent.mkdir(parents=True,exist_ok=True)
    # A second process must not operate on this deployment's shared database.
    process_lock=open(str(DB)+'.lock','a')
    fcntl.flock(process_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    with connect() as c:
        c.execute('pragma journal_mode=DELETE')
        seed(c);migrate(c)
    os.chmod(DB,0o600)
    server=ThreadingHTTPServer((BIND,PORT),Handler)
    server.daemon_threads=True
    def shutdown(signum,frame):
        threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,shutdown)
    threading.Thread(target=maintenance.scheduler,args=(sys.modules[__name__],),daemon=True).start()
    print(f'TiasTube: http://{BIND}:{PORT}',flush=True)
    try:server.serve_forever()
    finally:
        with maintenance.LOCK:server.server_close()
