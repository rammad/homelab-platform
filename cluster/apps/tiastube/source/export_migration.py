"""Export an existing app DB consistently; keep this private archive out of Git."""
import argparse,contextlib,os,sqlite3,tarfile,tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('database',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
if not a.database.is_file():raise SystemExit('Source database does not exist')
with tempfile.TemporaryDirectory() as tmp:
    copy=Path(tmp)/'tracearr.sqlite3'
    with contextlib.closing(sqlite3.connect(a.database)) as src,contextlib.closing(sqlite3.connect(copy)) as dst:
        src.backup(dst)
        if dst.execute('pragma integrity_check').fetchone()[0]!='ok':raise SystemExit('Integrity check failed')
    with os.fdopen(os.open(a.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as stream,tarfile.open(fileobj=stream,mode='w') as archive:
        archive.add(copy,arcname='tracearr.sqlite3')
        cfg=a.database.parent/'private'/a.database.stem/'tracearr.json'
        if cfg.exists():archive.add(cfg,arcname='private/tracearr/tracearr.json')
print('Private migration archive created:',a.output)
