#!/usr/bin/env python3
"""Build a deduplicated GitHub Actions matrix of manifest toolchain archives.

The clang prebuilt repositories carry every clang release they ever shipped, so
a whole-repo archive can exceed the 2 GiB GitHub release asset limit. Those
entries are therefore archived one clang-rXXXXXX subdirectory at a time, using
the compiler each device config actually points at.
"""
import json, pathlib, re, urllib.parse, xml.etree.ElementTree as ET
ROOT=pathlib.Path(__file__).resolve().parents[1]
labels={'clang/host/linux-x86':'clang','prebuilts/clang/host/linux-x86':'clang','prebuilts/rust':'rust','prebuilts/build-tools':'build-tools','kernel/prebuilts/build-tools':'build-tools'}

def clang_subdirs():
    """Map (oos dir, manifest file) -> clang-rXXXXXX dirs the configs of that manifest need."""
    result={}
    for path in sorted((ROOT/'configs').glob('oos*/*.json')):
        try: config=json.loads(path.read_text())
        except (OSError, ValueError): continue
        match=re.search(r'(clang-r[0-9A-Za-z]+)(?:/|$)',config.get('compiler') or config.get('c_compiler') or '')
        if not match: continue
        result.setdefault((path.parent.name,config.get('manifest','')),set()).add(match.group(1))
    return result

def archive_url(remote,name,revision):
    if 'github.com' in remote: return f'{remote}/{name}/archive/{urllib.parse.quote(revision,safe="")}.tar.gz'
    if 'googlesource.com' in remote: return f'{remote}/{name}/+archive/{urllib.parse.quote(revision,safe="")}.tar.gz'
    return f'{remote}/{name}/-/archive/{urllib.parse.quote(revision,safe="")}/{name.split("/")[-1]}-{revision}.tar.gz'

out={}
needed=clang_subdirs()
for path in sorted((ROOT/'manifests').glob('oos*/*.xml')):
    root=ET.parse(path).getroot(); remotes={r.get('name'):r.get('fetch','').rstrip('/') for r in root.findall('remote')}; default=root.find('default'); dremote=default.get('remote','') if default is not None else ''; drev=default.get('revision','') if default is not None else ''
    wanted=sorted(needed.get((path.parent.name,path.name),()))
    for p in root.findall('project'):
        name=p.get('name',''); label=next((v for k,v in labels.items() if k in name),None)
        if not label: continue
        remote=remotes.get(p.get('remote',dremote),''); rev=p.get('revision',drev)
        if not remote or not rev: continue
        # Clang is split per subdirectory; everything else is small enough to mirror whole.
        for subdir in (wanted if label=='clang' else [None]):
            filename=f'{label}-{rev}' + (f'-{subdir}' if subdir else '') + '.tar.gz'
            out[filename]={'name':name,'revision':rev,'label':label,'subdir':subdir or '','url':archive_url(remote,name,rev),'filename':filename}
print(json.dumps({'include':list(out.values())},separators=(',',':')))
