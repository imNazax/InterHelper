# Build on Linux x86_64 using the source tree as the working directory.
import shutil
import subprocess
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
model = root / 'models' / 'base.en'
if not (model / 'model.bin').is_file():
    raise SystemExit('Falta models/base.en. Ejecutá bash build_linux.sh.')

datas = [(str(model), 'models/base.en')]
binaries, hiddenimports = [], ['_cffi_backend', 'audio_capture_linux']
# Native runtimes and non-Python assets (SoundCard headers, VAD ONNX, etc.).
for package in ('faster_whisper', 'ctranslate2', 'av', 'tokenizers', 'onnxruntime', 'soundcard', 'pymupdf'):
    package_data, package_binaries, package_imports = collect_all(package)
    datas += package_data
    binaries += package_binaries
    hiddenimports += package_imports

# SoundCard dlopens libpulse through CFFI, so static import analysis cannot see it.
cache = subprocess.check_output([shutil.which('ldconfig') or '/sbin/ldconfig', '-p'], text=True)
pulse = next((Path(line.split('=>', 1)[1].strip()) for line in cache.splitlines()
              if line.strip().startswith('libpulse.so.0 ') and 'x86-64' in line), None)
if pulse is None:
    raise SystemExit('No se encontró libpulse.so.0 x86_64. Instalá la biblioteca PulseAudio del sistema.')
binaries.append((str(pulse), '.'))
for common in pulse.parent.glob('pulseaudio/libpulsecommon-*.so'):
    binaries.append((str(common), 'pulseaudio'))

a = Analysis([str(root / 'main.py')], pathex=[str(root)], binaries=binaries,
             datas=datas, hiddenimports=hiddenimports,
             excludes=['audio_capture_windows', 'torch', 'tensorflow', 'matplotlib', 'IPython'],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='InterHelper',
          debug=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='InterHelper')
