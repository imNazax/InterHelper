"""Export sources, portable runtime, AppImage and build versions together."""
import hashlib
import importlib.metadata
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parent.parent
dist = root / 'dist'
image = dist / 'InterHelper-x86_64.AppImage'
portable = dist / 'InterHelper'
if not image.is_file() or not (portable / 'InterHelper').is_file():
    raise SystemExit('Primero ejecutá bash build_linux.sh en Linux x86_64.')
versions = '\n'.join(sorted(f'{d.metadata["Name"]}=={d.version}' for d in importlib.metadata.distributions()))
(dist / 'build-versions.txt').write_text(versions + '\n', encoding='utf-8')
with image.open('rb') as stream:
    checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
(dist / 'SHA256SUMS').write_text(checksum + '  ' + image.name + '\n', encoding='utf-8')
output = dist / 'InterHelper-Linux-completo.zip'
with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
    archive.write(image, 'InterHelper/' + image.name)
    for f in sorted(portable.rglob('*')):
        if f.is_file():
            archive.write(f, 'InterHelper/portable/' + f.relative_to(portable).as_posix())
    sources = sorted(root.glob('*.py')) + sorted(root.glob('*.md'))
    sources += [root / 'requirements.txt', root / 'build_linux.sh']
    sources += sorted((root / 'packaging').glob('*'))
    sources += sorted((root / 'examples').glob('*'))
    for f in sources:
        if f.is_file():
            archive.write(f, 'InterHelper/fuentes/' + f.relative_to(root).as_posix())
    for name in ('build-versions.txt', 'SHA256SUMS'):
        archive.write(dist / name, 'InterHelper/' + name)
    archive.write(root / 'EXPORTAR-LINUX.md', 'InterHelper/LEEME.md')
print(f'Exportación completa: {output}')
