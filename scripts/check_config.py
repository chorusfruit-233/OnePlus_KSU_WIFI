#!/usr/bin/env python3
"""Validate device configuration, profile targets and source manifests."""
import argparse
import json
from pathlib import Path, PurePosixPath
import re
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def safe_relative(value):
    return isinstance(value, str) and bool(value) and not PurePosixPath(value).is_absolute() and '..' not in PurePosixPath(value).parts and '\\' not in value


def validate(path, profiles):
    errors = []
    try:
        config = json.loads(path.read_text())
    except (ValueError, OSError) as error:
        return [f'{path}: {error}']
    if not isinstance(config, dict):
        return [f'{path}: configuration must be an object']
    fields = ('model', 'soc', 'branch', 'manifest', 'android_version', 'kernel_version', 'os_version', 'arch', 'kernel_dir', 'defconfig', 'expected_release_prefix')
    for key in fields:
        if not isinstance(config.get(key), str) or not config[key]:
            errors.append(f'{path}: {key} must be a non-empty string')
    model = config.get('model', '')
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', model):
        errors.append(f'{path}: model must be a safe device identifier')
    if not isinstance(config.get('os_version'), str) or config['os_version'].lower() != path.parent.name:
        errors.append(f'{path}: os_version must match parent directory')
    if config.get('arch') != 'arm64':
        errors.append(f'{path}: only arm64 is supported')
    version = config.get('kernel_version', '')
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+', version):
        errors.append(f'{path}: invalid kernel_version')
    elif config.get('expected_release_prefix') != version + '.':
        errors.append(f'{path}: expected_release_prefix must be {version}.')
    for key in ('kernel_dir', 'manifest', 'defconfig'):
        if not safe_relative(config.get(key)):
            errors.append(f'{path}: {key} must be a safe relative path')
    if safe_relative(config.get('manifest')):
        manifest = ROOT / 'manifests' / path.parent.name / config['manifest']
        try:
            if ET.parse(manifest).getroot().tag != 'manifest':
                errors.append(f'{manifest}: root element must be manifest')
        except (ET.ParseError, OSError) as error:
            errors.append(f'{path}: invalid manifest: {error}')
    drivers = config.get('wifi_drivers')
    if not isinstance(drivers, list) or not drivers or any(not isinstance(x, str) for x in drivers):
        errors.append(f'{path}: wifi_drivers must be a non-empty string list')
    else:
        if len(drivers) != len(set(drivers)):
            errors.append(f'{path}: duplicate wifi_drivers')
        for driver in drivers:
            if driver not in profiles:
                errors.append(f'{path}: unknown wifi profile {driver}')
    if config.get('firmware_policy', 'warn') not in ('warn', 'require'):
        errors.append(f'{path}: firmware_policy must be warn or require')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('configs', nargs='*', type=Path)
    args = parser.parse_args()
    errors = []
    try:
        profiles = json.loads((ROOT / 'profiles/wifi-drivers.json').read_text())
        if not isinstance(profiles, dict) or not profiles:
            raise ValueError('profiles must be a non-empty object')
        for name, profile in profiles.items():
            if not isinstance(profile, dict):
                errors.append(f'profile {name}: must be an object')
                continue
            for field in ('kconfig', 'targets'):
                values = profile.get(field)
                if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v for v in values):
                    errors.append(f'profile {name}: {field} must be a non-empty string list')
            for target in profile.get('targets', []):
                if not safe_relative(target) or not target.endswith('.ko'):
                    errors.append(f'profile {name}: invalid target {target}')
            modules = profile.get('modules', [])
            if not isinstance(modules, list) or any(not isinstance(v, str) or not v.endswith('.ko') for v in modules):
                errors.append(f'profile {name}: modules must be a .ko filename list')
            elif any(Path(target).name not in modules for target in profile.get('targets', [])):
                errors.append(f'profile {name}: every target must be listed in modules')
            for symbol in profile.get('kconfig', []) + profile.get('dependencies', []) + profile.get('bool_kconfig', []):
                if not isinstance(symbol, str) or not re.fullmatch(r'CONFIG_[A-Za-z0-9_]+', symbol):
                    errors.append(f'profile {name}: invalid Kconfig symbol {symbol}')
            for optional in ('dependencies', 'bool_kconfig'):
                values = profile.get(optional, [])
                if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
                    errors.append(f'profile {name}: {optional} must be a string list')
            for firmware in profile.get('firmware', []):
                if not safe_relative(firmware):
                    errors.append(f'profile {name}: invalid firmware path {firmware}')
    except (OSError, ValueError) as error:
        parser.exit(1, f'invalid profiles: {error}\n')
    paths = sorted(args.configs or (ROOT / 'configs').glob('oos*/*.json'))
    if not paths:
        errors.append('no device configurations found')
    for path in paths:
        errors.extend(validate(path, profiles))
    if errors:
        parser.exit(1, '\n'.join(errors) + '\n')
    print(f'validated {len(paths)} device configs')


if __name__ == '__main__':
    main()
