#!/usr/bin/env python3
"""Fetch the kernel and toolchain projects required by a device manifest."""
import argparse, subprocess, xml.etree.ElementTree as ET
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
        if destination.exists(): subprocess.run(['rm','-rf',str(destination)],check=False)
        subprocess.run(['git','clone','--filter=blob:none',clone,str(destination)],check=True)
        subprocess.run(['git','-C',str(destination),'checkout','--detach',revision],check=True)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('manifest',type=Path); ap.add_argument('root',type=Path); args=ap.parse_args()
    tree=ET.parse(args.manifest).getroot(); remotes={r.get('name'):r.get('fetch','') for r in tree.findall('remote')}; default=tree.find('default'); dremote=default.get('remote','') if default is not None else ''; drev=default.get('revision','') if default is not None else ''
    for project in tree.findall('project'):
        path=project.get('path') or project.get('name');
        if path in ('.','./') or not any(x in path for x in ('kernel','clang','build-tools')): continue
        remote=project.get('remote',dremote); revision=project.get('revision',drev); base=remotes.get(remote,'').rstrip('/'); name=project.get('name')
        if not base or not revision or not name: continue
        print(f'sync {name} -> {path} @ {revision}',flush=True); fetch(f'{base}/{name}',revision,args.root/path)
if __name__=='__main__': main()
