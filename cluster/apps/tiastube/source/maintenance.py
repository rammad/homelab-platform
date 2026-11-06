"""Tracearr ingestion and SQLite recovery. No credentials in database backups."""
import contextlib, datetime as dt, functools, json, math, os, sqlite3, threading, time, urllib.request, urllib.error, urllib.parse, uuid
from pathlib import Path
from zoneinfo import ZoneInfo
LOCK=threading.RLock()
JOB=threading.Lock()
RUNTIME={'running':False,'progress':''}

def serialized(fn):
    @functools.wraps(fn)
    def wrapped(*args,**kwargs):
        with LOCK:return fn(*args,**kwargs)
    return wrapped

def now():return dt.datetime.now(dt.timezone.utc).isoformat()
def directory(db):
    p=Path(db).parent/'private'/Path(db).stem;p.mkdir(parents=True,exist_ok=True,mode=0o700);return p

def config(db):
    p=directory(db)/'tracearr.json'
    d=json.loads(p.read_text()) if p.exists() else {}
    return {'url':os.getenv('TRACEARR_URL',d.get('url','https://tracearr.example.com')), 'key':os.getenv('TRACEARR_API_KEY',d.get('key',''))}

def configure(db,d):
    url=d['url'].rstrip('/');u=urllib.parse.urlsplit(url)
    if u.scheme not in ('https','http') or not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in ('','/'):
        raise ValueError('Enter the Tracearr server URL, without an API path or credentials.')
    old=config(db)
    key=d.get('key','').strip() or old['key']
    if not key:raise ValueError('Enter a Tracearr API key.')
    if old['key'] and old['url']!=url:raise ValueError('Use a separate database when changing Tracearr servers.')
    p=directory(db)/'tracearr.json';tmp=p.with_suffix('.tmp')
    with os.fdopen(os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600),'w') as f:json.dump({'url':url,'key':key},f)
    os.replace(tmp,p)

def metadata(c,key,default=None):
    r=c.execute('select value from app_meta where key=?',(key,)).fetchone();return json.loads(r[0]) if r else default

def put(c,key,value):c.execute('insert into app_meta values(?,?) on conflict(key) do update set value=excluded.value',(key,json.dumps(value)))

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*a,**kw):return None

def request(cfg,path,params):
    url=cfg['url']+'/api/v1/public/'+path+'?'+urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            req=urllib.request.Request(url,headers={'Authorization':'Bearer '+cfg['key'],'Accept':'application/json'})
            with urllib.request.build_opener(NoRedirect).open(req,timeout=45) as r:return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code not in (429,500,502,503,504) or attempt==4:raise ValueError(f'Tracearr returned HTTP {e.code}. Check the URL and API key.') from None
            try:delay=min(60,max(1,int(e.headers.get('Retry-After','0'))))
            except ValueError:delay=0
        except (urllib.error.URLError,TimeoutError,OSError):
            if attempt==4:raise ValueError('Tracearr could not be reached after five attempts.') from None
            delay=0
        time.sleep(max(delay,2**attempt))

class PaginationChanged(ValueError):
    """A valid response whose offsets cannot form a complete unique snapshot."""

def _page_scan(cfg,resource,params,fetch,page_size,attempt):
    rows={};expected=None;received=0;overlaps=set()
    def read(page,size):
        nonlocal expected
        d=fetch(cfg,resource,{**(params or {}),'page':page,'pageSize':size})
        location=f'{resource} page {page}'
        if not isinstance(d,dict) or not isinstance(d.get('data'),list):
            raise ValueError(f'Invalid Tracearr response at {location}; no usage changes saved.')
        total=d.get('meta',{}).get('total')
        if type(total) is not int or total<0:
            raise ValueError(f'Missing Tracearr pagination total at {location}.')
        if expected is None:expected=total
        if total!=expected:
            raise PaginationChanged(f'{location}: record total changed from {expected} to {total}')
        for row in d['data']:
            if not isinstance(row,dict) or not isinstance(row.get('id'),str) or not row['id']:
                raise ValueError(f'Invalid Tracearr record ID at {location}; no usage changes saved.')
        return d['data']
    for page in range(1,100001):
        batch=read(page,page_size)
        for row in batch:
            if row['id'] in rows:overlaps.add(page)
            rows[row['id']]=row
        received+=len(batch)
        RUNTIME['progress']=f'{resource}: {len(rows):,} / {expected:,} (attempt {attempt}/3)'
        if received==expected:break
        if not batch or received>expected:
            raise PaginationChanged(f'{resource} page {page}: incomplete pagination')
        time.sleep(.1)
    else:raise ValueError(f'Tracearr {resource} page limit exceeded.')
    # Tied sort values can repeat an ID across two offsets and omit another.
    # Re-read the affected neighbourhood with shifted boundaries to recover the
    # missing IDs. Do not just ignore duplicates and accept a smaller import.
    if overlaps:
        size=page_size-3
        repair_pages=set()
        for page in overlaps:
            start=max(0,(page-2)*page_size)
            stop=min(expected,(page+1)*page_size)
            repair_pages.update(range(start//size+1,(stop-1)//size+2))
        for page in sorted(repair_pages):
            RUNTIME['progress']=f'{resource}: checking overlapping pages ({len(rows):,} / {expected:,})'
            for row in read(page,size):rows[row['id']]=row
            if len(rows)>expected:
                raise PaginationChanged(f'{resource} page {page}: record identities changed during scan')
            time.sleep(.1)
    if len(rows)!=expected:
        raise PaginationChanged(f'{resource} page {page}: only {len(rows)} unique records of {expected}')
    return list(rows.values())

def pages(cfg,resource,params=None,fetch=request):
    # Offset pages can shift during playback updates. Equal timestamps also have
    # no stable ID tie-breaker in Tracearr's history sort. Restart from page one
    # with different boundaries; never retain partial rows or hide duplicates.
    for attempt,page_size in enumerate((100,99,97),1):
        try:return _page_scan(cfg,resource,params,fetch,page_size,attempt)
        except PaginationChanged as error:
            if attempt==3:
                raise ValueError(f'Tracearr pagination stayed inconsistent after 3 attempts ({error}). No usage changes saved; try again after playback activity settles.') from None
            RUNTIME['progress']=f'{resource}: pagination shifted; restarting attempt {attempt+1}/3'
            time.sleep(attempt)


def ingest(c,users,history):
    for table,column in [('external_people','person'),('external_clients','client'),('external_sessions','session')]:
        c.execute(f'CREATE TABLE IF NOT EXISTS {table}(source TEXT PRIMARY KEY,{column} INTEGER)')
    def person(uid,name):
        row=c.execute('select person from external_people where source=?',(uid,)).fetchone()
        if row:return row[0]
        aid=c.execute('insert into accounts(name) values(?)',(name,)).lastrowid
        pid=c.execute('insert into people(name,account_id) values(?,?)',(name,aid)).lastrowid
        c.execute('insert into external_people values(?,?)',(uid,pid));return pid
    for u in users:person(u['id'],u.get('displayName') or u.get('username') or 'Unknown')
    changed=set();added=updated=0
    for s in history:
        try:
            sid=s['id'];uid=s['user']['id'];stamp=dt.datetime.fromisoformat(s['startedAt'].replace('Z','+00:00'))
            minutes=float(s['durationMs'])/60000
            if not uid or stamp.tzinfo is None or not math.isfinite(minutes) or minutes<0:raise ValueError()
        except (KeyError,TypeError,ValueError):raise ValueError('Invalid playback record; the entire import was rolled back.') from None
        month=stamp.astimezone(ZoneInfo('America/Los_Angeles')).strftime('%Y-%m')
        pid=person(uid,s['user'].get('username') or 'Unknown')
        identity=json.dumps([s.get('serverId'),uid,s.get('device'),s.get('player'),s.get('product'),s.get('platform')])
        row=c.execute('select client from external_clients where source=?',(identity,)).fetchone()
        if row:cid=row[0]
        else:
            name=' / '.join(dict.fromkeys(str(s[k]) for k in ['device','player','product','platform'] if s.get(k))) or 'Unknown client'
            cid=c.execute("insert into clients(person,name,device) values(?,?,'')",(pid,name)).lastrowid
            c.execute('insert into external_clients values(?,?)',(identity,cid))
        row=c.execute('select s.* from sessions s join external_sessions e on e.session=s.id where e.source=?',(sid,)).fetchone()
        if row:
            if (row['client'],row['month'],row['minutes'])!=(cid,month,minutes):
                changed.update([month,row['month']]);updated+=1
                c.execute('update sessions set client=?,month=?,minutes=? where id=?',(cid,month,minutes,row['id']))
        else:
            ident=c.execute('insert into sessions(client,month,minutes) values(?,?,?)',(cid,month,minutes)).lastrowid
            c.execute('insert into external_sessions values(?,?)',(sid,ident));changed.add(month);added+=1
    flagged=set(metadata(c,'sync_changed_approvals',[]))
    flagged.update(r[0] for r in c.execute('select month from approvals') if r[0] in changed)
    put(c,'sync_changed_approvals',sorted(flagged))
    return {'fetched':len(history),'added':added,'updated':updated}

@serialized
def backup(db,label='manual'):
    folder=directory(db)/'backups';folder.mkdir(exist_ok=True,mode=0o700)
    name=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+label+'-'+uuid.uuid4().hex[:8]+'.sqlite3'
    path=folder/name;tmp=path.with_suffix('.tmp')
    try:
        with contextlib.closing(sqlite3.connect(db)) as src,contextlib.closing(sqlite3.connect(tmp)) as dst:
            src.backup(dst)
            if dst.execute('pragma integrity_check').fetchone()[0]!='ok':raise ValueError('Backup integrity check failed.')
        os.chmod(tmp,0o600);os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)
    if label=='daily':
        for old in sorted(folder.glob('*-daily-*.sqlite3'),reverse=True)[30:]:old.unlink()
    return name

def backup_path(db,name):
    if Path(name).name!=name or not name.endswith('.sqlite3'):raise ValueError('Invalid backup name.')
    p=directory(db)/'backups'/name
    if not p.is_file():raise ValueError('Backup not found.')
    return p

@serialized
def restore(db,name):
    if not JOB.acquire(blocking=False):raise ValueError('Wait for the running sync to finish before restoring.')
    try:
        path=backup_path(db,name)
        with contextlib.closing(sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)) as src:
            if src.execute('pragma integrity_check').fetchone()[0]!='ok':raise ValueError('Backup is damaged.')
            with contextlib.closing(sqlite3.connect(db)) as current:
                # Restore only this app's compatible schema, before touching live data.
                for table,sql in current.execute("select name,sql from sqlite_master where type='table' and name not like 'sqlite_%'"):
                    expected=[(r[1],r[2]) for r in current.execute('pragma table_info('+table+')')]
                    actual=[(r[1],r[2]) for r in src.execute('pragma table_info('+table+')')]
                    if expected!=actual:raise ValueError('Backup schema differs from this app version; use the offline migration procedure.')
            safety=backup(db,'before-restore')
            with contextlib.closing(sqlite3.connect(db)) as dst:src.backup(dst)
        return safety
    finally:JOB.release()

def status(app):
    cfg=config(app.DB)
    with contextlib.closing(app.connect()) as c:
        result=metadata(c,'sync_status',{})
        result={**result,'changed_approvals':metadata(c,'sync_changed_approvals',[])}
    folder=directory(app.DB)/'backups'
    return {**result,**RUNTIME,'configured':bool(cfg['key']),'url':cfg['url'], 'backups':[{'name':p.name,'bytes':p.stat().st_size} for p in sorted(folder.glob('*.sqlite3'),reverse=True)]}

def run_sync(app,full=False,fetch=request):
    try:
        cfg=config(app.DB)
        if not cfg['key']:raise ValueError('Configure the Tracearr API key first.')
        with LOCK,contextlib.closing(app.connect()) as c:previous=metadata(c,'sync_status',{})
        started=now();last=previous.get('last_success')
        full=full or not last or not previous.get('last_full') or (dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(previous['last_full'])).days>=7
        params={'state':'stopped','timezone':'America/Los_Angeles','endDate':dt.datetime.now(ZoneInfo('America/Los_Angeles')).isoformat()}
        if not full:params['startDate']=(dt.datetime.fromisoformat(last)-dt.timedelta(days=45)).isoformat()
        users=pages(cfg,'users',fetch=fetch);history=pages(cfg,'history',params,fetch)
        with LOCK:
            backup(app.DB,'before-sync') if full else None
            with contextlib.closing(app.connect()) as c, c:
                result=ingest(c,users,history)
                put(c,'sync_status',{**previous,**result,'last_success':started,'last_attempt':started,'last_full':started if full else previous.get('last_full'),'error':None,'mode':'full' if full else '45-day overlap'})
    except Exception as e:
        # Never return raw network exception text: it can contain secret-bearing URLs.
        message=str(e) if isinstance(e,ValueError) else 'Sync failed ('+type(e).__name__+'). Existing data was kept.'
        with LOCK,contextlib.closing(app.connect()) as c,c:
            put(c,'sync_status',{**metadata(c,'sync_status',{}),'last_attempt':now(),'error':message})
    finally:RUNTIME.update(running=False,progress='');JOB.release()

def start_sync(app,full=False):
    if not JOB.acquire(blocking=False):raise ValueError('A sync or restore is already running.')
    RUNTIME.update(running=True,progress='Connecting to Tracearr…')
    threading.Thread(target=run_sync,args=(app,full),daemon=True).start()

def scheduler(app):
    while True:
        try:
            with LOCK,contextlib.closing(app.connect()) as c,c:
                today=dt.datetime.now(ZoneInfo('America/Los_Angeles')).date().isoformat()
                if metadata(c,'last_daily_backup')!=today:
                    backup(app.DB,'daily');put(c,'last_daily_backup',today)
                previous=metadata(c,'sync_status',{})
            attempted=previous.get('last_attempt')
            if config(app.DB)['key'] and (not attempted or (dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(attempted)).total_seconds()>=3600):
                if not RUNTIME['running']:start_sync(app)
            RUNTIME.pop('maintenance_error',None)
        except Exception as e:RUNTIME['maintenance_error']='Automatic maintenance failed: '+type(e).__name__
        time.sleep(60)

@serialized
def upload(db,content):
    if not content.startswith(b'SQLite format 3\x00'):raise ValueError('Select a SQLite backup downloaded from this app.')
    folder=directory(db)/'backups';folder.mkdir(exist_ok=True,mode=0o700)
    name=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S')+'-uploaded-'+uuid.uuid4().hex[:8]+'.sqlite3'
    path=folder/name
    try:
        with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as f:f.write(content)
        with contextlib.closing(sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)) as c:
            if c.execute('pragma integrity_check').fetchone()[0]!='ok':raise ValueError('Backup failed its integrity check.')
            for table in ['people','entries','subscriptions','sessions','accounts','devices','app_meta']:
                if not c.execute("select 1 from sqlite_master where type='table' and name=?",(table,)).fetchone():raise ValueError('This is not a compatible TiasTube backup.')
        return name
    except Exception:
        path.unlink(missing_ok=True);raise ValueError('The file is not a valid TiasTube database backup.') from None
