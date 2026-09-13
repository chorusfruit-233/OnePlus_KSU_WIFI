#!/usr/bin/env python3
"""Package the complete dependency closure and a deterministic load order."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def fail(message):
    raise ValueError(message)


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def module_name(path):
    return Path(path).name.removesuffix('.ko').replace('-', '_')


def parse_symvers(path):
    result = {}
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 3:
            result[parts[1]] = (int(parts[0], 16), parts[2])
    return result


def package(config_path, kernel, install, output):
    config = json.loads(config_path.read_text())
    profiles = json.loads((ROOT / 'profiles/wifi-drivers.json').read_text())
    release_file = kernel / 'include/config/kernel.release'
    if not release_file.is_file():
        release_file = kernel / 'kernel.release'
    if not release_file.is_file():
        fail(f'missing generated kernel.release in {kernel}')
    release = release_file.read_text().strip()
    prefix = config['expected_release_prefix']
    if not release or not prefix or not release.startswith(prefix) or '/' in release:
        fail(f'kernelrelease {release!r} does not match {prefix!r}')
    symvers = kernel / 'target.Module.symvers'
    if not symvers.is_file():
        symvers = kernel / 'Module.symvers'
    if not symvers.is_file() or not symvers.stat().st_size:
        fail('missing target Module.symvers')
    target_symbols = parse_symvers(symvers)
    build_symbols = parse_symvers(kernel / 'wifi.Module.symvers') if (kernel / 'wifi.Module.symvers').is_file() else {}
    module_root = install / 'lib/modules' / release
    if not module_root.is_dir():
        fail(f'no installed modules for {release}: {module_root}')
    module_paths = sorted(module_root.rglob('*.ko'))
    metadata = {}
    by_name = {}
    for path in module_paths:
        name = command('modinfo', '-F', 'name', str(path)).replace('-', '_')
        if not re.fullmatch(r'[A-Za-z0-9_]+', name):
            fail(f'invalid module name: {path}: {name!r}')
        if name in by_name:
            fail(f'duplicate module name {name}: {by_name[name]}, {path}')
        by_name[name] = path
        metadata[path] = {'name': name}
    builtins = set()
    for builtin_file in (module_root / 'modules.builtin', kernel / 'modules.builtin'):
        if builtin_file.is_file():
            builtins.update(module_name(p) for p in builtin_file.read_text().splitlines())
    requested = []
    for profile_name in config['wifi_drivers']:
        for target in profiles[profile_name]['targets']:
            matches = [p for p in module_paths if p.as_posix().endswith('/' + target)]
            if len(matches) != 1:
                fail(f'requested module must be produced exactly once: {target} (found {len(matches)})')
            if matches[0] not in requested:
                requested.append(matches[0])
    if not requested:
        fail('no requested modules')

    ordered = []
    visiting = set()
    visited = set()
    expected_vermagic = None
    target_config = (kernel / 'target.config') if (kernel / 'target.config').is_file() else kernel / '.config'
    modversions = 'CONFIG_MODVERSIONS=y' in target_config.read_text().splitlines()

    def visit(path):
        nonlocal expected_vermagic
        if path in visited:
            return
        if path in visiting:
            fail(f'circular module dependency: {path}')
        visiting.add(path)
        data = path.read_bytes()[:20]
        machine = int.from_bytes(data[18:20], 'little' if data[5:6] == b'\x01' else 'big')
        if data[:4] != b'\x7fELF' or (config.get('arch', 'arm64') == 'arm64' and machine != 183):
            fail(f'not an AArch64 ELF module: {path}')
        magic = command('modinfo', '-F', 'vermagic', str(path))
        if not magic or magic.split()[0] != release:
            fail(f'module vermagic mismatch: {path}: {magic!r}, expected {release}')
        if expected_vermagic is None:
            expected_vermagic = magic
        elif expected_vermagic != magic:
            fail(f'modules have different vermagic: {path}')
        dependencies = command('modinfo', '-F', 'depends', str(path)).split(',')
        for dependency in filter(None, dependencies):
            dependency = dependency.strip().replace('-', '_')
            if dependency in builtins:
                continue
            if dependency not in by_name:
                fail(f'missing dependency {dependency} needed by {path.name}; include its matching .ko in the input module directory')
            visit(by_name[dependency])
        if modversions:
            versions = command('modprobe', '--show-modversions', str(path))
            if not versions:
                fail(f'CONFIG_MODVERSIONS=y but no symbol versions in {path}')
            for line in versions.splitlines():
                crc, symbol = line.split()[:2]
                expected = target_symbols.get(symbol) or build_symbols.get(symbol)
                if expected is None or int(crc, 16) != expected[0]:
                    fail(f'symbol CRC mismatch or unavailable export in {path.name}: {symbol}')
        visiting.remove(path)
        visited.add(path)
        ordered.append(path)

    for path in requested:
        visit(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='wifi-lkm-') as temporary:
        staging = Path(temporary)
        (staging / 'modules').mkdir()
        (staging / 'firmware').mkdir()
        basenames = set()
        for path in ordered:
            if path.name in basenames:
                fail(f'module filename collision: {path.name}')
            basenames.add(path.name)
            shutil.copy2(path, staging / 'modules' / path.name)
        (staging / 'modules.load').write_text(''.join(f'modules/{path.name}\n' for path in ordered))
        (staging / 'kernel.release').write_text(release + '\n')
        (staging / 'kernel.vermagic').write_text(expected_vermagic + '\n')
        shutil.copy2(config_path, staging / 'config.json')
        shutil.copy2(symvers, staging / 'Module.symvers')
        for template in (ROOT / 'module-template').iterdir():
            if template.is_file():
                shutil.copy2(template, staging / template.name)
        props = (staging / 'module.prop').read_text()
        props = re.sub(r'^name=.*$', f"name=OnePlus {config['model']} {config['os_version']} WiFi LKM", props, flags=re.M)
        props = re.sub(r'^version=.*$', f'version=0.2-{release}', props, flags=re.M)
        props = re.sub(r'^versionCode=.*$', 'versionCode=2', props, flags=re.M)
        (staging / 'module.prop').write_text(props)
        firmware_families = sorted({f for n in config['wifi_drivers'] for f in profiles[n].get('firmware', [])})
        firmware_dir = Path(os.environ['FIRMWARE_DIR']).resolve() if os.environ.get('FIRMWARE_DIR') else None
        missing_firmware = []
        for family in firmware_families:
            source = firmware_dir / family if firmware_dir else None
            if source is not None and source.is_dir():
                shutil.copytree(source, staging / 'firmware' / family, dirs_exist_ok=True)
            elif source is not None and source.is_file():
                destination = staging / 'firmware' / family
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            else:
                missing_firmware.append(family)
        (staging / 'firmware.required').write_text(''.join(f'{family}\n' for family in firmware_families))
        if missing_firmware:
            message = 'firmware not bundled (may already exist on device): ' + ', '.join(missing_firmware)
            if config.get('firmware_policy', 'warn') == 'require':
                fail(message)
            print('warning: ' + message)
        temporary_zip = output.with_name(output.name + '.tmp')
        try:
            with zipfile.ZipFile(temporary_zip, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(staging.rglob('*')):
                    if path.is_file():
                        if path.suffix == '.sh':
                            path.chmod(0o755)
                        archive.write(path, path.relative_to(staging))
            temporary_zip.replace(output)
        finally:
            temporary_zip.unlink(missing_ok=True)
    print(f'packaged {len(ordered)} modules for {config["model"]}: {output}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('kernel', type=Path)
    parser.add_argument('install', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        package(args.config.resolve(), args.kernel.resolve(), args.install.resolve(), args.output.resolve())
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'package error: {error}\n')


if __name__ == '__main__':
    main()
