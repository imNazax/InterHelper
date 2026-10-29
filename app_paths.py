"""Writable Linux user configuration; keep Windows preferences location."""
import os
import sys
from pathlib import Path


def settings_path():
    if sys.platform.startswith('linux'):
        root = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
        if not root.is_absolute():
            root = Path.home() / '.config'
        return str(root / 'interhelper' / 'interhelper_settings.json')
    return str(Path(__file__).resolve().parent / 'interhelper_settings.json')


def model_source(name='base.en'):
    """Use the bundled model; source execution can use Whisper's download cache."""
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    local = root / 'models' / name
    if (local / 'model.bin').is_file():
        return str(local)
    if getattr(sys, 'frozen', False):
        raise RuntimeError(f'Falta el modelo incluido: {local}. Volvé a generar el paquete.')
    return name
