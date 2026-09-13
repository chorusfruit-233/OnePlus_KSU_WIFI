#!/usr/bin/env python3
"""Fetch the kernel and toolchain projects required by a device manifest."""
import argparse, os, shutil, subprocess, urllib.request, tarfile, xml.etree.ElementTree as ET
from pathlib import Path

def fetch(url, revision, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if (destination/'.git').exists():
        subprocess.run(['git','-C',str(destination),'fetch','--depth=1','origin',revision],check=True)
        subprocess.run(['git','-C',str(destination),'checkout','--detach','FETCH_HEAD'],check=True)
        return
    clone=url.rstrip('/') + ('' if url.endswith('.git') else '.git')
    try:
        subprocess.run(['git','clone','--filter=blob:none','--depth=1','--branch',revision,clone,str(destination)],check=True)
    except subprocess.CalledProcessError:
        if destination.exists(): shutil.rmtree(destination)
        subprocess.run(['git','clone','--filter=blob:none',clone,str(destination)],check=True)
        subprocess.run(['git','-C',str(destination),'checkout','--detach',revision],check=True)

def cached_fetch(label, revision, destination):
    base=os.environ.get('TOOLCHAIN_CACHE_URL','').rstrip('/')
    if not base: return False
    filename=f'{label}-{revision}.tar.gz'; url=f'{base}/{filename}'
    try:
        archive=destination.parent/(filename+'.download'); destination.mkdir(parents=True,exist_ok=True)
        urllib.request.urlretrieve(url,archive)
        with tarfile.open(archive,'r:gz') as tf:
            members=[m for m in tf.getmembers() if m.name and not m.name.startswith('/') and '..' not in Path(m.name).parts]
            prefixes={Path(m.name).parts[0] for m in members if Path(m.name).parts}
            strip=1 if len(prefixes)==1 else 0
            for member in members:
                parts=Path(member.name).parts[strip:]
                if not parts: continue
                member.name='/'.join(parts)
                tf.extract(member,destination,filter='data')
        archive.unlink(); return True
    except Exception as error:
        print(f'cache miss {filename}: {error}',flush=True)
        if archive.exists(): archive.unlink()
        return False

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('manifest',type=Path); ap.add_argument('root',type=Path); args=ap.parse_args()
    tree=ET.parse(args.manifest).getroot(); remotes={r.get('name'):r.get('fetch','') for r in tree.findall('remote')}; default=tree.find('default'); dremote=default.get('remote','') if default is not None else ''; drev=default.get('revision','') if default is not None else ''
    for project in tree.findall('project'):
        path=project.get('path') or project.get('name');
        if path in ('.','./') or not any(x in path for x in ('kernel','clang','build-tools')): continue
        remote=project.get('remote',dremote); revision=project.get('revision',drev); base=remotes.get(remote,'').rstrip('/'); name=project.get('name')
        label=next((v for k,v in {'clang/host/linux-x86':'clang','prebuilts/clang/host/linux-x86':'clang','prebuilts/rust':'rust','prebuilts/build-tools':'build-tools','kernel/prebuilts/build-tools':'build-tools'}.items() if k in name),None)
        if not base or not revision or not name: continue
        print(f'sync {name} -> {path} @ {revision}',flush=True)
        destination=args.root/path
        if label and cached_fetch(label, revision, destination): continue
        fetch(f'{base}/{name}',revision,destination)
if __name__=='__main__': main()
