import os, subprocess, tempfile
from pathlib import Path
script=str(Path(__file__).resolve().parents[1] / 'backup-postgres.sh')
for scenario in ['success','dump-fail','verify-fail','wrong-marker','locked']:
 with tempfile.TemporaryDirectory() as t:
  p=Path(t); dest=p/'dest'; dest.mkdir(); bins=p/'bin'; bins.mkdir()
  (dest/'.backup-target').write_text('wrong' if scenario=='wrong-marker' else 'homelab-cluster-backups-v1')
  if scenario=='locked': (dest/'immich/.lock').mkdir(parents=True)
  commands={'pg_dump': '''#!/bin/sh
if [ "$1" = --version ]; then echo pg_dump-test; exit 0; fi
[ "$SCENARIO" != dump-fail ] || exit 1
for arg do case "$arg" in --file=*) printf testdump > "${arg#--file=}";; esac; done
''','pg_restore':'''#!/bin/sh
[ "$SCENARIO" != verify-fail ] || exit 1
echo 'TABLE DATA'
''','psql':'#!/bin/sh\necho version-test\n'}
  for name,body in commands.items():
   f=bins/name; f.write_text(body); f.chmod(0o700)
  env={**os.environ,'PATH':str(bins)+':'+os.environ['PATH'],'BACKUP_ROOT':str(dest),'APP':'immich','PGHOST':'fake','PGUSER':'fake','PGDATABASE':'fake','PGPASSWORD':'test-secret','SCENARIO':scenario}
  result=subprocess.run(['sh',script],env=env,capture_output=True,text=True)
  assert (result.returncode==0)==(scenario=='success'),(scenario,result.stderr)
  completed=list(dest.glob('immich/*/completed-at.txt'))
  assert len(completed)==(1 if scenario=='success' else 0)
  assert 'test-secret' not in result.stdout+result.stderr
  if scenario!='locked': assert not (dest/'immich/.lock').exists()
  print('PASS',scenario)
