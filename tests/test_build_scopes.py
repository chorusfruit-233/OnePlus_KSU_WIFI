#!/usr/bin/env python3
"""Guards the external module tree layout against headers shared between siblings."""
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('wifi_build', ROOT / 'scripts/build_lkm.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class AncestorMaterializationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='wifi build tests ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'kernel'
        self.external = self.root / 'wifi-source'
        self.external.mkdir(parents=True)
        # rtl8187 keeps the shared rtl818x.h one directory above its own sources and
        # reaches it with `-I $(srctree)/$(src)/..`.
        driver = self.source / 'drivers/net/wireless/realtek/rtl818x/rtl8187'
        driver.mkdir(parents=True)
        (driver / 'Makefile').write_text('ccflags-y += -I $(srctree)/$(src)/..\n')
        (driver / 'dev.c').write_text('int dev;\n')
        (driver.parent / 'rtl818x.h').write_text('/* shared */\n')
        (driver.parent / 'Makefile').write_text('obj-$(CONFIG_RTL8187) += rtl8187/\n')
        (self.source / 'Makefile').write_text('# kernel top level\n')
        self.scope = 'drivers/net/wireless/realtek/rtl818x/rtl8187'
        shutil.copytree(self.source / self.scope, self.external / self.scope)

    def test_sibling_header_becomes_reachable(self):
        build.materialize_ancestors(self.external, self.source, [self.scope])
        self.assertTrue((self.external / self.scope).parent.joinpath('rtl818x.h').is_file())

    def test_external_root_stays_free_for_the_generated_kbuild(self):
        build.materialize_ancestors(self.external, self.source, [self.scope])
        self.assertFalse((self.external / 'Makefile').exists())


if __name__ == '__main__':
    unittest.main()
