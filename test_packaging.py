"""Packaging contracts: frozen model stays local; export contains all deliverables."""
from pathlib import Path
import runpy
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import patch
import app_paths


class PackagingTests(unittest.TestCase):
    def test_frozen_model_uses_local_bundle(self):
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / 'models' / 'base.en'
            model.mkdir(parents=True)
            (model / 'model.bin').write_bytes(b'fixture')
            with patch.object(app_paths.sys, 'frozen', True, create=True), patch.object(app_paths.sys, '_MEIPASS', folder, create=True):
                self.assertEqual(app_paths.model_source(), str(model))

    def test_frozen_missing_model_fails_instead_of_downloading(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(app_paths.sys, 'frozen', True, create=True), patch.object(app_paths.sys, '_MEIPASS', folder, create=True):
                with self.assertRaisesRegex(RuntimeError, 'Falta el modelo'):
                    app_paths.model_source()

    def test_export_contains_appimage_portable_model_and_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'packaging').mkdir()
            (root / 'dist' / 'InterHelper' / '_internal' / 'models' / 'base.en').mkdir(parents=True)
            (root / 'dist' / 'InterHelper' / 'InterHelper').write_bytes(b'fake executable')
            (root / 'dist' / 'InterHelper' / '_internal' / 'models' / 'base.en' / 'model.bin').write_bytes(b'fake model')
            (root / 'dist' / 'InterHelper-x86_64.AppImage').write_bytes(b'fake AppImage')
            for name in ('main.py', 'requirements.txt', 'build_linux.sh', 'EXPORTAR-LINUX.md'):
                (root / name).write_text('fixture', encoding='utf-8')
            script = root / 'packaging' / 'export_release.py'
            shutil.copyfile(Path(__file__).parent / 'packaging' / 'export_release.py', script)
            runpy.run_path(str(script), run_name='__main__')
            with zipfile.ZipFile(root / 'dist' / 'InterHelper-Linux-completo.zip') as archive:
                files = archive.namelist()
            for name in ('InterHelper/InterHelper-x86_64.AppImage',
                         'InterHelper/portable/InterHelper',
                         'InterHelper/portable/_internal/models/base.en/model.bin',
                         'InterHelper/fuentes/main.py', 'InterHelper/SHA256SUMS'):
                self.assertIn(name, files)


if __name__ == '__main__':
    unittest.main()
