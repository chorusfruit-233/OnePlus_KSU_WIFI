#!/usr/bin/env python3
"""Compile copied in-tree module sources against the target symbol contract."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run(*args, **kwargs):
    print('+ ' + ' '.join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), check=True, **kwargs)


def config_values(path):
    result = {}
    for line in path.read_text().splitlines():
        match = re.fullmatch(r'(CONFIG_\w+)=(.*)', line)
        if match:
            result[match[1]] = match[2]
    return result


def env_path(name, default):
    return Path(os.environ.get(name) or default).expanduser().resolve()


def build(config_path, checkout, output):
    run(sys.executable, ROOT / 'scripts/check_config.py', config_path)
    config = json.loads(config_path.read_text())
    profiles = json.loads((ROOT / 'profiles/wifi-drivers.json').read_text())
    kernel = checkout / config['kernel_dir']
    if not (kernel / 'Makefile').is_file() and (checkout / 'Makefile').is_file():
        kernel = checkout
    if not (kernel / 'Makefile').is_file():
        raise ValueError(f'kernel source directory missing: {kernel}')
    kernel = kernel.resolve()
    target = env_path('KERNEL_BUILD_DIR', kernel)
    target_config = env_path('KERNEL_CONFIG', target / '.config')
    target_symvers = env_path('KERNEL_SYMVERS', target / 'Module.symvers')
    for path in (target_config, target_symvers):
        if not path.is_file() or not path.stat().st_size:
            raise ValueError(f'missing target ABI input: {path}')
    baseline = config_values(target_config)
    if baseline.get('CONFIG_MODULES') != 'y':
        raise ValueError('target kernel does not enable CONFIG_MODULES')
    release = os.environ.get('KERNEL_RELEASE', '').strip()
    for path in (target / 'include/config/kernel.release', target / 'kernel.release'):
        if not release and path.is_file():
            release = path.read_text().strip()
    if not release or not release.startswith(config['expected_release_prefix']):
        raise ValueError('provide the exact target KERNEL_RELEASE or generated include/config/kernel.release; a version prefix is insufficient')
    if not re.fullmatch(r'[A-Za-z0-9_.+\-]+', release):
        raise ValueError('invalid KERNEL_RELEASE')
    for tool in ('make', 'modinfo', 'modprobe'):
        if not shutil.which(tool):
            raise ValueError(f'{tool} is required')
    compiler = os.environ.get('CLANG_BIN') or config.get('compiler') or config.get('c_compiler')
    if compiler:
        compiler = Path(compiler).expanduser()
        if not compiler.is_absolute():
            compiler = checkout / compiler
        if not (compiler / 'clang').is_file():
            toolchain = compiler.parent.name
            matches = list(checkout.glob(f'**/{toolchain}/bin/clang')) if toolchain else []
            if matches:
                compiler = matches[0].parent
        if not (compiler / 'clang').is_file():
            raise ValueError(f'matching clang toolchain missing: {compiler}; set CLANG_BIN')
        os.environ['PATH'] = str(compiler.resolve()) + os.pathsep + os.environ['PATH']
    if not shutil.which('clang'):
        raise ValueError('clang is required')
    module_key = os.environ.get('MODULE_SIGN_KEY')
    module_cert = os.environ.get('MODULE_SIGN_CERT')
    if bool(module_key) != bool(module_cert):
        raise ValueError('MODULE_SIGN_KEY and MODULE_SIGN_CERT must be provided together')
    if baseline.get('CONFIG_MODULE_SIG_FORCE') == 'y' and not module_key:
        raise ValueError('target enforces signatures; provide its trusted MODULE_SIGN_KEY and MODULE_SIGN_CERT')
    device_output = output / config['os_version'].lower() / config_path.stem
    device_output.mkdir(parents=True, exist_ok=True)
    # A fresh work directory prevents stale .ko files from satisfying missing targets.
    work = Path(tempfile.mkdtemp(prefix='build-', dir=device_output))
    print(f'build workspace: {work}', flush=True)
    obj = work / 'kernel-out'
    obj.mkdir()
    shutil.copy2(target_config, obj / '.config')
    shutil.copy2(target_config, obj / 'target.config')
    shutil.copy2(target_symvers, obj / 'target.Module.symvers')
    for name in ('modules.builtin', 'modules.builtin.modinfo'):
        if (target / name).is_file():
            shutil.copy2(target / name, obj / name)
    # Kbuild rejects O= when .config/generated headers exist in the source tree.
    # Snapshot only in that case; never clean or edit the caller's checkout.
    source = kernel
    if (kernel / '.config').exists() or (kernel / 'include/config').exists() or (kernel / 'arch/arm64/include/generated').exists():
        source = work / 'kernel-source'
        if work == kernel or kernel in work.parents:
            raise ValueError('OUT must be outside the kernel source tree')
        print('copying prepared source tree into isolated workspace', flush=True)
        ignored = shutil.ignore_patterns('.git', '.config', '.config.old', '*.o', '*.ko', '*.a', '*.cmd')
        shutil.copytree(kernel, source, symlinks=True, ignore=ignored)
        for relative in ('include/config', 'include/generated', 'arch/arm64/include/generated'):
            path = source / relative
            if path.is_dir():
                shutil.rmtree(path)
        # Preserve SCM identity without updating the original repository index.
        if (kernel / '.git').exists():
            gitdir = subprocess.check_output(['git', '-C', str(kernel), 'rev-parse', '--absolute-git-dir'], text=True).strip()
            (source / '.git').write_text('gitdir: ' + gitdir + '\n')
        os.environ['GIT_OPTIONAL_LOCKS'] = '0'
    jobs = os.environ.get('JOBS', str(os.cpu_count() or 1))
    if not jobs.isdigit() or int(jobs) < 1:
        raise ValueError('JOBS must be a positive integer')
    make = ['make', '-C', str(source), f'O={obj}', 'ARCH=arm64', 'LLVM=1', 'LLVM_IAS=1', f'-j{jobs}']
    if os.environ.get('CCACHE_DIR'):
        os.environ['CCACHE_DIR'] = str(Path(os.environ['CCACHE_DIR']).expanduser().resolve())
        os.environ.setdefault('CCACHE_BASEDIR', str(ROOT))
        make.extend(['CC=ccache clang', 'HOSTCC=ccache clang', 'HOSTCXX=ccache clang++'])
    # Allow standard cross compiler variables without inventing target ABI values.
    for name in ('CROSS_COMPILE', 'CROSS_COMPILE_COMPAT'):
        if os.environ.get(name):
            make.append(f'{name}={os.environ[name]}')
    requested = set()
    prerequisite_modules = set()
    bools = set()
    targets = []
    for profile_name in config['wifi_drivers']:
        profile = profiles[profile_name]
        requested.update(profile['kconfig'])
        prerequisite_modules.update(profile.get('dependencies', []))
        bools.update(profile.get('bool_kconfig', []))
        targets.extend(profile['targets'])
    config_script = source / 'scripts/config'
    if not config_script.is_file():
        raise ValueError(f'missing Kconfig helper: {config_script}')
    for symbol in sorted(requested | prerequisite_modules):
        if baseline.get(symbol) == 'y':
            if symbol in requested:
                raise ValueError(f'{symbol} is already built into the target kernel; choose a disabled driver')
            continue
        run(config_script, '--file', obj / '.config', '--module', symbol)
    for symbol in sorted(bools):
        if baseline.get(symbol) == 'm':
            raise ValueError(f'{symbol} is modular in the target; refusing to convert it to built-in')
        run(config_script, '--file', obj / '.config', '--enable', symbol)
    run(*make, 'olddefconfig')
    current = config_values(obj / '.config')
    missing = sorted(s for s in requested if current.get(s) != 'm')
    if missing:
        raise ValueError('Kconfig did not enable the requested modules (missing symbols/dependencies): ' + ', '.join(missing))
    # Existing ABI settings cannot change, even as an olddefconfig side effect.
    changed = [f'{key}: {value} -> {current.get(key, "n")}' for key, value in baseline.items()
               if value != 'n' and current.get(key, 'n') != value]
    if changed:
        raise ValueError('target configuration drift after olddefconfig:\n' + '\n'.join(changed))
    # New module-selected booleans are captured for review; baseline values stay intact.
    (obj / 'config.diff').write_text(''.join(f'{k}={v}\n' for k, v in sorted(current.items()) if baseline.get(k, 'n') != v))
    run(*make, 'modules_prepare')
    actual_release = (obj / 'include/config/kernel.release').read_text().strip()
    if actual_release != release:
        raise ValueError(f'kernelrelease mismatch: built {actual_release!r}, target {release!r}; use the exact source revision/build localversion')
    # Build these in-tree directories as ONE external module set. This makes
    # modpost consume target Module.symvers, including on kernels >= 6.6.
    # Full `make modules` instead tries to regenerate the running kernel ABI.
    scopes = {str(Path(t).parent) for t in targets}
    added_modules = {k for k, v in current.items() if v == 'm' and baseline.get(k) != 'm'}
    makefiles = list(source.rglob('Makefile')) + list(source.rglob('Kbuild'))
    for makefile in makefiles:
        relative = makefile.parent.relative_to(source)
        if not relative.parts or relative.parts[0] in ('.git', 'scripts', 'tools', 'samples'):
            continue
        try:
            text = makefile.read_text(errors='replace')
        except OSError:
            continue
        symbols = set(re.findall(r'(?:obj|lib)-\$\((CONFIG_[A-Za-z0-9_]+)\)', text))
        if added_modules & symbols:
            scopes.add(relative.as_posix())
    scopes = sorted(p for p in scopes if not any(p.startswith(q + '/') for q in scopes if p != q))
    external = work / 'wifi-source'
    external.mkdir()
    for scope in scopes:
        source_path = source / scope
        if not source_path.is_dir() or not ((source_path / 'Makefile').is_file() or (source_path / 'Kbuild').is_file()):
            raise ValueError(f'missing driver source directory: {source_path}')
        shutil.copytree(source_path, external / scope, symlinks=False,
                        ignore=shutil.ignore_patterns('*.o', '*.ko', '*.a', '*.cmd', '*.mod', '*.mod.c', 'Module.symvers', 'modules.order'))
    (external / 'Kbuild').write_text('obj-m += ' + ' '.join(scope + '/' for scope in scopes) + '\n')
    # Existing modular providers inside these scopes are rebuilt as a set. Remove
    # their duplicate exports from modpost input, then verify their CRCs below.
    target_lines = target_symvers.read_text().splitlines()
    filtered = []
    for line in target_lines:
        fields = line.split()
        if len(fields) < 3:
            continue
        owner = fields[2].removesuffix('.ko')
        if not any(owner.startswith(scope + '/') for scope in scopes):
            filtered.append(line)
    (obj / 'Module.symvers').write_text('\n'.join(filtered) + '\n')
    run(*make, f'M={external}', 'modules')
    produced_symvers = external / 'Module.symvers'
    if not produced_symvers.is_file():
        raise ValueError('external modpost did not produce Module.symvers')
    from package_module import parse_symvers
    original_symbols = parse_symvers(target_symvers)
    built_symbols = parse_symvers(produced_symvers)
    for symbol, (crc, _) in built_symbols.items():
        if symbol in original_symbols and crc != original_symbols[symbol][0]:
            raise ValueError(f'rebuilt dependency changes target symbol ABI: {symbol}')
    shutil.copy2(produced_symvers, obj / 'wifi.Module.symvers')
    shutil.copy2(target_symvers, obj / 'Module.symvers')
    install = work / 'install'
    module_root = install / 'lib/modules' / release
    extra = module_root / 'extra'
    extra.mkdir(parents=True)
    for module in external.rglob('*.ko'):
        destination = extra / module.relative_to(external)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(module, destination)
        if module_key:
            run(obj / 'scripts/sign-file', 'sha256', Path(module_key).resolve(), Path(module_cert).resolve(), destination)
    # Existing target modules can satisfy dependencies outside the build scopes.
    if os.environ.get('KERNEL_MODULES_DIR'):
        originals = Path(os.environ['KERNEL_MODULES_DIR']).resolve()
        if not originals.is_dir():
            raise ValueError(f'KERNEL_MODULES_DIR missing: {originals}')
        rebuilt_names = {p.name for p in extra.rglob('*.ko')}
        for module in originals.rglob('*.ko'):
            if module.name not in rebuilt_names:
                destination = module_root / 'target' / module.relative_to(originals)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(module, destination)
    for name in ('modules.builtin', 'modules.builtin.modinfo'):
        if (obj / name).is_file():
            shutil.copy2(obj / name, module_root / name)
    output_zip = device_output / f'{config_path.stem}-{config["os_version"].lower()}-wifi-lkm.zip'
    run(ROOT / 'scripts/package_module.sh', config_path, obj, install, output_zip)
    if os.environ.get('KEEP_BUILD', '0') != '1':
        shutil.rmtree(work)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('kernel_tree', nargs='?', default=os.environ.get('KERNEL_TREE'))
    parser.add_argument('output', nargs='?', type=Path, default=Path('dist'))
    args = parser.parse_args()
    if not args.kernel_tree:
        parser.error('kernel tree is required as an argument or KERNEL_TREE')
    try:
        build(args.config.resolve(), Path(args.kernel_tree).expanduser().resolve(), args.output.resolve())
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'build error: {error}\n')


if __name__ == '__main__':
    main()
