#!/usr/bin/env python3
"""Build a deduplicated GitHub Actions matrix of manifest toolchain archives."""
import json, pathlib, urllib.parse, xml.etree.ElementTree as ET
ROOT=pathlib.Path(__file__).resolve().parents[1]
labels={'clang/host/linux-x86':'clang','prebuilts/clang/host/linux-x86':'clang','prebuilts/rust':'rust','prebuilts/build-tools':'build-tools','kernel/prebuilts/build-tools':'build-tools'}
out={}
for path in sorted((ROOT/'manifests').glob('oos*/*.xml')):
    root=ET.parse(path).getroot(); remotes={r.get('name'):r.get('fetch','').rstrip('/') for r in root.findall('remote')}; default=root.find('default'); dremote=default.get('remote','') if default is not None else ''; drev=default.get('revision','') if default is not None else ''
    for p in root.findall('project'):
        name=p.get('name',''); label=next((v for k,v in labels.items() if k in name),None)
        if not label: continue
        remote=remotes.get(p.get('remote',dremote),''); rev=p.get('revision',drev)
        if not remote or not rev: continue
        filename=f'{label}-{rev}.tar.gz'
        if 'github.com' in remote: url=f'{remote}/{name}/archive/{urllib.parse.quote(rev,safe="")}.tar.gz'
        elif 'googlesource.com' in remote: url=f'{remote}/{name}/+archive/{urllib.parse.quote(rev,safe="")}.tar.gz'
        else: url=f'{remote}/{name}/-/archive/{urllib.parse.quote(rev,safe="")}/{name.split("/")[-1]}-{rev}.tar.gz'
        out[filename]={'name':name,'revision':rev,'label':label,'url':url,'filename':filename}
print(json.dumps({'include':list(out.values())},separators=(',',':')))
