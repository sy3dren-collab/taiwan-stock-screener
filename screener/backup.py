"""Atomic SQLite snapshots, checksummed compressed parts below GitHub's file limit."""
import argparse,gzip,hashlib,json,os,shutil,sqlite3,tempfile
from pathlib import Path


def save(db,directory,part_bytes=40*1024*1024):
    if part_bytes<=0 or part_bytes>40*1024*1024:raise ValueError('備份分片最多40MiB')
    directory=Path(directory);directory.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory.parent) as t:
        temp=Path(t);snapshot=temp/'snapshot.db';source=sqlite3.connect(db);dest=sqlite3.connect(snapshot)
        try:source.backup(dest)
        finally:source.close();dest.close()
        verify=sqlite3.connect(snapshot)
        try:
            if verify.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('備份SQLite完整性失敗')
        finally:verify.close()
        archive=temp/'prices.gz'
        with snapshot.open('rb') as inp,archive.open('wb') as out:
            with gzip.GzipFile(filename='',mode='wb',fileobj=out,mtime=0) as gz:shutil.copyfileobj(inp,gz)
        parts=[]
        with archive.open('rb') as inp:
            while chunk:=inp.read(part_bytes):
                digest=hashlib.sha256(chunk).hexdigest();name=f'prices.{digest}.part{len(parts):04d}';(temp/name).write_bytes(chunk)
                parts.append({'name':name,'sha256':hashlib.sha256(chunk).hexdigest(),'bytes':len(chunk)})
        with snapshot.open('rb') as inp:sqlite_sha=hashlib.file_digest(inp,'sha256').hexdigest()
        manifest={'schema_version':1,'format':'sqlite-gzip-split','parts':parts,'sqlite_sha256':sqlite_sha}
        # The new manifest becomes visible only after all its immutable parts exist.
        directory.mkdir(exist_ok=True)
        old_names=set()
        old=directory/'manifest.json'
        if old.exists():old_names={p['name'] for p in json.loads(old.read_text())['parts']}
        for part in parts:shutil.copyfile(temp/part['name'],directory/part['name'])
        pending=directory/'manifest.json.tmp';pending.write_text(json.dumps(manifest,indent=2)+'\n');pending.replace(old)
        for name in old_names-{p['name'] for p in parts}:
            if Path(name).name==name and name.startswith('prices.'):(directory/name).unlink(missing_ok=True)
        return manifest


def restore(directory,db):
    directory=Path(directory);manifest=json.loads((directory/'manifest.json').read_text());target=Path(db);target.parent.mkdir(parents=True,exist_ok=True)
    if manifest.get('schema_version')!=1 or manifest.get('format')!='sqlite-gzip-split' or not manifest.get('parts'):raise ValueError('不支援的備份格式')
    names=[p['name'] for p in manifest['parts']]
    import re
    if any(not re.fullmatch('[0-9a-f]{64}',part.get('sha256','')) or part['name']!=f"prices.{part['sha256']}.part{i:04d}" for i,part in enumerate(manifest['parts'])):raise ValueError('備份分片名稱／順序不合法')
    with tempfile.TemporaryDirectory(dir=target.parent) as t:
        temp=Path(t);archive=temp/'prices.gz'
        with archive.open('wb') as out:
            for part in manifest['parts']:
                data=(directory/part['name']).read_bytes()
                if len(data)!=part['bytes'] or hashlib.sha256(data).hexdigest()!=part['sha256']:raise ValueError('備份分片校驗失敗')
                out.write(data)
        restored=temp/'restored.db'
        with gzip.open(archive,'rb') as inp,restored.open('wb') as out:shutil.copyfileobj(inp,out)
        with restored.open('rb') as inp:
            if hashlib.file_digest(inp,'sha256').hexdigest()!=manifest['sqlite_sha256']:raise ValueError('還原SQLite雜湊不符')
        check=sqlite3.connect(restored)
        try:
            if check.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('還原SQLite完整性失敗')
        finally:check.close()
        os.replace(restored,target)
    return manifest


def main():
    p=argparse.ArgumentParser(description='官方SQLite原子快照及40MiB分片備份')
    p.add_argument('command',choices=['save','restore']);p.add_argument('--db',default='.state/prices.sqlite3');p.add_argument('--directory',default='.state/backup')
    a=p.parse_args();r=save(a.db,a.directory) if a.command=='save' else restore(a.directory,a.db)
    print('verified backup parts:',len(r['parts']))

if __name__=='__main__':main()
