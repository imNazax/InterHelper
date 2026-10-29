# Empaquetar y exportar InterHelper para Linux

## Build completo

Desde una terminal de tu sesión gráfica, dentro de la carpeta del proyecto:

```bash
bash build_linux.sh
```

Requisitos: Linux x86_64, Python 3.10 o posterior con venv y Tkinter, `ldconfig`,
la biblioteca `libpulse`, conexión a Internet y espacio libre. En Fedora, si falta
Tkinter: `sudo dnf install python3-tkinter`. No ejecutes el build con sudo.

El script crea o reutiliza `.venv` de ESTA carpeta, instala las dependencias y
PyInstaller, ejecuta las pruebas, descarga `base.en` y genera el portable.
Después comprueba su funcionamiento local, construye la AppImage, la comprueba
y crea la exportación completa. Las pruebas de interfaz requieren una pantalla.

## Resultados

- `dist/InterHelper/`: carpeta portable completa. Ejecutar `InterHelper`.
- `dist/InterHelper-x86_64.AppImage`: ejecutable en un archivo.
- `dist/InterHelper-Linux-completo.zip`: AppImage, portable, fuentes,
  instrucciones, versiones de dependencias y checksum SHA256.

Los ejecutables incluyen Python, dependencias y `base.en` para CPU/int8.
No necesitan pip ni conexión para transcribir. Las preferencias y las guías
personales no se incluyen en la exportación. Se eligen al abrir la aplicación.

```bash
chmod +x dist/InterHelper-x86_64.AppImage
./dist/InterHelper-x86_64.AppImage
```

Si el montaje de la AppImage falla por FUSE:

```bash
APPIMAGE_EXTRACT_AND_RUN=1 ./dist/InterHelper-x86_64.AppImage
```

También se puede usar el portable directamente:

```bash
./dist/InterHelper/InterHelper
```

Después de extraer el ZIP, si el gestor no conservó los permisos del portable,
restaurarlos con `chmod +x portable/InterHelper`.

## Repetir solo el empaquetado

Si el portable ya existe y falló la etapa de AppImage o exportación:

```bash
bash build_linux.sh --package-only
```

Este modo reutiliza `dist/InterHelper`, elimina el AppDir generado anterior y
repite los chequeos y el empaquetado. No recompila el portable ni descarga el
modelo. Si cambiaste el código o las dependencias, usá el build completo.

El AppDir usa enlaces físicos a los archivos del portable para evitar duplicar
su contenido: `.build` y `dist` deben estar en el mismo sistema de archivos.
La AppImage, su extracción de prueba y el ZIP final sí necesitan espacio extra.
El script comprueba espacio e inodos antes de empaquetar y muestra una estimación
conservadora. Si falta capacidad, liberar espacio o ampliar el disco de la VM.

## Chequeo del paquete

```bash
./dist/InterHelper/InterHelper --self-check
APPIMAGE_EXTRACT_AND_RUN=1 ./dist/InterHelper-x86_64.AppImage --self-check
```

El chequeo carga el modelo local, ejecuta Whisper en CPU y VAD, comprueba Tcl y
la biblioteca de audio y crea un PDF para leerlo con el mismo importador de guías.
No reemplaza una prueba de captura real. Abrí la aplicación, cargá una guía y
reproducí voz por la salida seleccionada para completar esa prueba.

PyMuPDF está fijado en 1.26.7 para conservar el lector de texto usado por el
proyecto y evitar los recursos de Layout incorporados en la versión 2.0.
Después de actualizar las fuentes, reconstruí el paquete: instalar dependencias
con pip no modifica una AppImage ya creada.

## Estado BETA y compatibilidad

La captura de salida y la transcripción se probaron en Fedora 44 KDE. El
micrófono Linux queda pendiente de prueba en un equipo físico y la compatibilidad
entre distros sigue en validación.

La AppImage no garantiza funcionar en todo Linux. Un build hecho en Fedora
puede requerir una glibc más reciente que la de otra distro. Para ampliar soporte,
reconstruir sobre la base Linux mínima elegida y probar el mismo archivo en las
distros objetivo. Se requiere una sesión PulseAudio o PipeWire con pipewire-pulse,
y un escritorio X11/XWayland para Tkinter. No se incluye GPU ni CUDA.

La descarga usa appimagetool oficial 1.9.1 y comprueba su SHA256. Para usar una
copia específica previamente descargada:

```bash
APPIMAGETOOL=/ruta/appimagetool-x86_64.AppImage bash build_linux.sh
```

Referencias: [PyInstaller](https://pyinstaller.org/en/stable/usage.html),
[appimagetool](https://github.com/AppImage/appimagetool/releases/tag/1.9.1),
[PyMuPDF 1.26.7](https://pypi.org/project/pymupdf/1.26.7/).
