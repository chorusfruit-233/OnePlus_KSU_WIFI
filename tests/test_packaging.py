#!/usr/bin/env python3
"""Packaging regression tests; fake ELF files stand in for cross-compiled modules."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('wifi_package', ROOT / 'scripts/package_module.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class PackagingTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='wifi package tests ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.kernel = self.root / 'kernel'
        self.kernel.mkdir()
        self.release = '6.1.75-test'
        (self.kernel / 'kernel.release').write_text(self.release + '\n')
        (self.kernel / '.config').write_text('CONFIG_MODVERSIONS=y\n')
        (self.kernel / 'Module.symvers').write_text('0x12345678\tmodule_layout\tvmlinux\tEXPORT_SYMBOL\n')
        self.config = self.root / 'device.json'
        self.write_config(['usb-wifi'])
        self.install = self.root / 'install'
        self.modules = self.install / 'lib/modules' / self.release
        self.output = self.root / 'output with space' / 'device.zip'
        self.metadata = {}
        self.add_module('drivers/net/wireless/realtek/rtl8xxxu/rtl8xxxu.ko', 'rtl8xxxu', 'mac80211')
        self.add_module('net/mac80211/mac80211.ko', 'mac80211', 'cfg80211')
        self.add_module('net/wireless/cfg80211.ko', 'cfg80211', '')

    def write_config(self, drivers, **overrides):
        data = {'model': 'OP12', 'os_version': 'OOS16', 'expected_release_prefix': '6.1.',
                'arch': 'arm64', 'wifi_drivers': drivers, 'firmware_policy': 'warn'}
        data.update(overrides)
        self.config.write_text(json.dumps(data))

    def add_module(self, relative, name, dependencies):
        path = self.modules / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        elf = bytearray(20)
        elf[:6] = b'\x7fELF\x02\x01'
        elf[18:20] = (183).to_bytes(2, 'little')
        path.write_bytes(elf)
        self.metadata[str(path)] = {'name': name, 'depends': dependencies, 'vermagic': self.release + ' SMP preempt mod_unload modversions aarch64'}
        return path

    def command(self, *args):
        if args[0] == 'modinfo':
            return self.metadata[args[-1]][args[2]]
        if args[0] == 'modprobe':
            return '0x12345678 module_layout'
        raise AssertionError(args)

    def run_package(self, root=None):
        with patch.object(package, 'command', self.command):
            if root is None:
                package.package(self.config, self.kernel, self.install, self.output)
            else:
                with patch.object(package, 'ROOT', root):
                    package.package(self.config, self.kernel, self.install, self.output)

    def test_transitive_dependencies_and_relative_paths(self):
        self.run_package()
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(archive.read('modules.load').decode().splitlines(),
                             ['modules/cfg80211.ko', 'modules/mac80211.ko', 'modules/rtl8xxxu.ko'])
            self.assertIn('service.sh', archive.namelist())
            self.assertIn('Module.symvers', archive.namelist())

    def test_absent_optional_targets_are_skipped(self):
        """Only one of the 17 usb-wifi candidates exists in this tree."""
        self.run_package()
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(sorted(n for n in archive.namelist() if n.startswith('modules/')),
                             ['modules/cfg80211.ko', 'modules/mac80211.ko', 'modules/rtl8xxxu.ko'])

    def test_no_candidate_present_fails(self):
        (self.modules / 'drivers/net/wireless/realtek/rtl8xxxu/rtl8xxxu.ko').unlink()
        with self.assertRaisesRegex(ValueError, 'no requested modules'):
            self.run_package()
        self.assertFalse(self.output.exists())

    def test_required_profile_still_demands_its_target(self):
        """A profile without the optional flag keeps the strict check."""
        fake_root = self.root / 'repo'
        (fake_root / 'profiles').mkdir(parents=True)
        (fake_root / 'profiles/wifi-drivers.json').write_text(json.dumps({'required': {
            'kconfig': ['CONFIG_RTL8XXXU'],
            'targets': ['drivers/net/wireless/realtek/rtl8xxxu/rtl8xxxu.ko']}}))
        shutil.copytree(ROOT / 'module-template', fake_root / 'module-template')
        self.write_config(['required'])
        (self.modules / 'drivers/net/wireless/realtek/rtl8xxxu/rtl8xxxu.ko').unlink()
        with self.assertRaisesRegex(ValueError, 'requested module must be produced'):
            self.run_package(root=fake_root)
        self.assertFalse(self.output.exists())

    def test_missing_dependency_fails(self):
        (self.modules / 'net/wireless/cfg80211.ko').unlink()
        with self.assertRaisesRegex(ValueError, 'missing dependency cfg80211'):
            self.run_package()

    def test_cycle_fails(self):
        self.metadata[str(self.modules / 'net/wireless/cfg80211.ko')]['depends'] = 'rtl8xxxu'
        with self.assertRaisesRegex(ValueError, 'circular module dependency'):
            self.run_package()

    def test_wrong_vermagic_fails(self):
        self.metadata[str(self.modules / 'net/mac80211/mac80211.ko')]['vermagic'] = '6.1.76 SMP'
        with self.assertRaisesRegex(ValueError, 'vermagic mismatch'):
            self.run_package()

    def test_wrong_crc_fails(self):
        (self.kernel / 'Module.symvers').write_text('0xabcdef00\tmodule_layout\tvmlinux\tEXPORT_SYMBOL\n')
        with self.assertRaisesRegex(ValueError, 'symbol CRC mismatch'):
            self.run_package()

    def test_repack_replaces_stale_zip_members(self):
        self.output.parent.mkdir(parents=True)
        with zipfile.ZipFile(self.output, 'w') as archive:
            archive.writestr('stale.ko', b'old')
        self.run_package()
        with zipfile.ZipFile(self.output) as archive:
            self.assertNotIn('stale.ko', archive.namelist())


if __name__ == '__main__':
    unittest.main()
