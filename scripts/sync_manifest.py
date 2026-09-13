#!/usr/bin/env python3
"""Fetch the kernel and toolchain projects required by a device manifest."""
import argparse, json, os, re, shutil, subprocess, urllib.request, tarfile, xml.etree.ElementTree as ET
from pathlib import Path

LABELS={'clang/host/linux-x86':'clang','prebuilts/clang/host/linux-x86':'clang','prebuilts/rust':'rust','prebuilts/build-tools':'build-tools','kernel/prebuilts/build-tools':'build-tools'}

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

def extract(archive, destination, strip_prefix):
    """Unpack a cached archive, rejecting traversal and (optionally) the git-archive root dir."""
    with tarfile.open(archive,'r:gz') as tf:
        members=[m for m in tf.getmembers() if m.name and not m.name.startswith('/') and '..' not in Path(m.name).parts]
        strip=0
        if strip_prefix:
            prefixes={Path(m.name).parts[0] for m in members if Path(m.name).parts}
            strip=1 if len(prefixes)==1 else 0
        for member in members:
            parts=Path(member.name).parts[strip:]
            if not parts: continue
            member.name='/'.join(parts)
            tf.extract(member,destination,filter='data')

def cached_fetch(label, revision, destination, subdir=None):
    """Prefer the pruned subdir archive; fall back to a whole-repo archive."""
    base=os.environ.get('TOOLCHAIN_CACHE_URL','').rstrip('/')
    if not base: return False
    candidates=[]
    # A pruned archive already stores repo-relative paths, so it must not be stripped.
    if subdir: candidates.append((f'{label}-{revision}-{subdir}.tar.gz',False))
    candidates.append((f'{label}-{revision}.tar.gz',True))
    for filename, strip_prefix in candidates:
        archive=destination.parent/(filename+'.download')
        try:
            destination.mkdir(parents=True,exist_ok=True)
            urllib.request.urlretrieve(f'{base}/{filename}',archive)
            extract(archive,destination,strip_prefix)
            archive.unlink(); return True
        except Exception as error:
            print(f'cache miss {filename}: {error}',flush=True)
            if archive.exists(): archive.unlink()
    return False

def config_clang_subdir(path):
    """The clang-rXXXXXX directory a device config expects inside the prebuilt repo."""
    if not path: return None
    try:
        config=json.loads(Path(path).read_text())
    except (OSError, ValueError) as error:
        print(f'ignoring config {path}: {error}',flush=True); return None
    match=re.search(r'(clang-r[0-9A-Za-z]+)(?:/|$)',config.get('compiler') or config.get('c_compiler') or '')
    return match.group(1) if match else None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('manifest',type=Path)
    ap.add_argument('root',type=Path)
    ap.add_argument('--config',type=Path,help='device config selecting the required clang subdirectory')
    args=ap.parse_args()
    clang_subdir=config_clang_subdir(args.config)
    if clang_subdir: print(f'clang subdirectory for this device: {clang_subdir}',flush=True)
    tree=ET.parse(args.manifest).getroot(); remotes={r.get('name'):r.get('fetch','') for r in tree.findall('remote')}; default=tree.find('default'); dremote=default.get('remote','') if default is not None else ''; drev=default.get('revision','') if default is not None else ''
    for project in tree.findall('project'):
        path=project.get('path') or project.get('name')
        if path in ('.','./') or not any(x in path for x in ('kernel','clang','build-tools')): continue
        remote=project.get('remote',dremote); revision=project.get('revision',drev); base=remotes.get(remote,'').rstrip('/'); name=project.get('name')
        label=next((v for k,v in LABELS.items() if k in name),None)
        if not base or not revision or not name: continue
        print(f'sync {name} -> {path} @ {revision}',flush=True)
        destination=args.root/path
        subdir=clang_subdir if label=='clang' else None
        if label and cached_fetch(label,revision,destination,subdir): continue
        fetch(f'{base}/{name}',revision,destination)
if __name__=='__main__': main()
