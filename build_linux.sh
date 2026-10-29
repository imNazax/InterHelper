#!/usr/bin/env bash
# Run from the exported source folder: bash build_linux.sh
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
    echo 'Este build requiere Linux x86_64.' >&2
    exit 1
fi
case "${1:-}" in
    ""|--package-only) ;;
    *) echo 'Uso: bash build_linux.sh [--package-only]' >&2; exit 1 ;;
esac
mkdir -p "$ROOT/.build" "$ROOT/dist"
APPDIR="$ROOT/.build/InterHelper.AppDir"
if [[ -d "$APPDIR" ]]; then
    # This is a fixed generated folder underneath this project.
    rm -rf -- "$ROOT/.build/InterHelper.AppDir"
fi
if [[ "${1:-}" != --package-only ]]; then
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
    python3 -m venv "$ROOT/.venv"
fi
PYTHON="$ROOT/.venv/bin/python"
"$PYTHON" -c 'import tkinter; tkinter.Tcl(); print("Tk/Tcl disponible")' || {
    echo 'Instalá Tkinter del sistema (en Fedora: sudo dnf install python3-tkinter).' >&2
    exit 1
}
"$PYTHON" -m pip install -r requirements.txt 'PyInstaller>=6,<7'
"$PYTHON" -m unittest test_audio_linux test_guias test_packaging
"$PYTHON" - <<'PY'
from pathlib import Path
from faster_whisper.utils import download_model
from faster_whisper import WhisperModel
model = Path('models/base.en')
print('Preparando base.en para uso sin conexión...', flush=True)
download_model('base.en', output_dir=str(model))
WhisperModel(str(model), device='cpu', compute_type='int8', local_files_only=True)
PY
"$PYTHON" -m PyInstaller --noconfirm --clean --distpath "$ROOT/dist" \
    --workpath "$ROOT/.build/pyinstaller" "$ROOT/packaging/InterHelper.spec"
# CFFI may fall back to this unversioned filename.
ln -sf libpulse.so.0 "$ROOT/dist/InterHelper/_internal/libpulse.so"
fi
PYTHON="$ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON" || ! -x "$ROOT/dist/InterHelper/InterHelper" ]]; then
    echo "Falta el portable. Ejecutá primero bash build_linux.sh." >&2
    exit 1
fi

"$PYTHON" - <<'PY'
from pathlib import Path
import os
import shutil
root = Path.cwd()
size = sum(f.stat().st_size for f in (root / 'dist/InterHelper').rglob('*') if f.is_file())
# Conservative allowance for AppImage, extraction and the complete ZIP.
required = 3 * size + 256 * 1024 * 1024
available = shutil.disk_usage(root).free
fs = os.statvfs(root)
if available < required or (fs.f_files and not fs.f_favail):
    raise SystemExit(f'Espacio insuficiente para empaquetar: {available / 2**30:.1f} GiB libres; '
                     f'reservá aproximadamente {required / 2**30:.1f} GiB y verificá df -i. '
                     'Liberá espacio y repetí con --package-only.')
PY
HF_HUB_OFFLINE=1 "$ROOT/dist/InterHelper/InterHelper" --self-check
mkdir -p "$APPDIR"
# Same project filesystem: share immutable payload files instead of copying them.
cp -al "$ROOT/dist/InterHelper/." "$APPDIR/" || {
    echo 'No se pudieron crear enlaces físicos. .build y dist deben estar en el mismo sistema de archivos.' >&2
    exit 1
}
cp "$ROOT/packaging/interhelper.desktop" "$APPDIR/"
cp "$ROOT/packaging/interhelper.svg" "$APPDIR/"
cat > "$APPDIR/AppRun" <<'SH'
#!/bin/sh
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "$HERE/InterHelper" "$@"
SH
chmod +x "$APPDIR/AppRun"

TOOL="${APPIMAGETOOL:-$ROOT/.build/appimagetool-x86_64.AppImage}"
if [[ ! -f "$TOOL" ]]; then
    "$PYTHON" - "$TOOL" <<'PY'
from pathlib import Path
from urllib.request import urlretrieve
import hashlib
import sys
path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
url = 'https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage'
print('Descargando appimagetool oficial...', flush=True)
temporary = path.with_suffix('.download')
urlretrieve(url, temporary)
with temporary.open('rb') as stream:
    checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
if checksum != 'ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0':
    raise SystemExit('La descarga de appimagetool no coincide con su SHA256 publicado.')
temporary.replace(path)
PY
fi
chmod +x "$TOOL"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" "$APPDIR" "$ROOT/dist/InterHelper-x86_64.AppImage"
HF_HUB_OFFLINE=1 APPIMAGE_EXTRACT_AND_RUN=1 "$ROOT/dist/InterHelper-x86_64.AppImage" --self-check
"$PYTHON" packaging/export_release.py
printf '\nListo: %s\n' "$ROOT/dist/InterHelper-Linux-completo.zip"
printf 'AppImage: %s\nPortable: %s\n' "$ROOT/dist/InterHelper-x86_64.AppImage" "$ROOT/dist/InterHelper/InterHelper"
