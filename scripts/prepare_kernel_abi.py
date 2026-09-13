#!/usr/bin/env python3
"""Prepare a complete out-of-tree kernel ABI for the CI LKM build."""
import argparse, json, os, shutil, subprocess
from pathlib import Path
ap=argparse.ArgumentParser(); ap.add_argument('config',type=Path); ap.add_argument('root',type=Path); a=ap.parse_args()
c=json.loads(a.config.read_text()); k=a.root/c['kernel_dir']; k=k if (k/'Makefile').is_file() else a.root
jobs=os.environ.get('JOBS',str(os.cpu_count() or 2)); arch=c.get('arch','arm64'); out=Path(os.environ.get('KERNEL_BUILD_DIR',str(k/'out'))); out.mkdir(parents=True,exist_ok=True)
compiler=os.environ.get('CLANG_BIN') or c.get('compiler') or c.get('c_compiler')
if compiler:
    compiler=Path(compiler).expanduser(); compiler=compiler if compiler.is_absolute() else a.root/compiler
    if not (compiler/'clang').is_file():
        toolchain=Path(compiler).parent.name
        matches=list(a.root.glob(f'**/{toolchain}/bin/clang')) if toolchain else []
        if matches: compiler=matches[0].parent
    if not (compiler/'clang').is_file(): raise SystemExit(f'clang toolchain missing: {compiler}')
    os.environ['PATH']=str(compiler.resolve())+os.pathsep+os.environ['PATH']
if not shutil.which('clang'): raise SystemExit('clang is required')
def make(*targets):
    args=['make','-C',str(k),f'O={out}',f'ARCH={arch}','LLVM=1','LLVM_IAS=1',f'-j{jobs}']
    if os.environ.get('CCACHE_DIR'): args.extend(['CC=ccache clang','HOSTCC=ccache clang','HOSTCXX=ccache clang++'])
    subprocess.run(args+list(targets),check=True)
config=os.environ.get('KERNEL_CONFIG')
if config: shutil.copy2(config,out/'.config')
if not (out/'.config').exists(): make(c.get('defconfig','gki_defconfig'))
make('olddefconfig','modules_prepare','modules')
release_file=out/'include/config/kernel.release'
symvers=out/'Module.symvers'
if not release_file.is_file() or not release_file.read_text().strip(): raise SystemExit('kernel.release was not generated')
release=release_file.read_text().strip()
if not release.startswith(c['expected_release_prefix']): raise SystemExit(f'release {release} does not match {c["expected_release_prefix"]}')
if not symvers.is_file() or not symvers.stat().st_size: raise SystemExit('Module.symvers was not generated; complete kernel build is required')
print(f'prepared ABI: {release} ({symvers.stat().st_size} bytes)')
