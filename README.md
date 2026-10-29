# InterHelper

![Windows compatible](https://img.shields.io/badge/Windows-compatible-2ea44f)
![Linux BETA](https://img.shields.io/badge/Linux-BETA-f2c811)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776ab)
![Local](https://img.shields.io/badge/Transcripci%C3%B3n-local-216e43)

**Asistente de escritorio que escucha una conversación, reconoce preguntas de tu guía y muestra las respuestas que preparaste.**

InterHelper está pensado para consultar tus propias notas durante entrevistas, practicar respuestas y encontrar información en una guía sin tener que buscarla manualmente en medio de una conversación. Funciona con Python y Tkinter, transcribe en CPU mediante faster-whisper y compara lo escuchado con las preguntas del documento que abriste.

## ¿Cómo funciona?

1. Preparás una guía con preguntas y respuestas.
2. La abrís en InterHelper: PDF, DOCX, JSON o TXT.
3. Elegís la salida de audio que querés escuchar y, opcionalmente, tu micrófono.
4. InterHelper transcribe el audio y busca coincidencias en esa guía.
5. La ventana muestra la pregunta detectada y tu respuesta preparada.

Las respuestas salen de tu documento. La aplicación no genera respuestas nuevas ni habla por vos. Cada guía reemplaza el catálogo activo; no hay preguntas de empresas precargadas.

## Compatibilidad

| Plataforma | Estado | Audio |
| --- | --- | --- |
| Windows | ✅ Compatible | Captura de salida completa mediante WASAPI; micrófono opcional. |
| Linux x86_64 | 🧪 **BETA** | PulseAudio o PipeWire con `pipewire-pulse`; captura de salida y transcripción probadas en Fedora 44 KDE. |

En Linux, el micrófono queda pendiente de validación en una máquina física: la VM usada para las pruebas no recibía señal de entrada. La AppImage está disponible como formato de build; la compatibilidad entre distintas distros sigue en pruebas. Una AppImage construida en Fedora puede requerir bibliotecas más recientes que las de otros sistemas.

## Funciones

- Importación de guías PDF, DOCX, TXT y JSON.
- Captura de **toda la mezcla de la salida seleccionada**, incluyendo el audio de una llamada, un navegador o un reproductor que use esa salida.
- Micrófono opcional y separado del audio de salida.
- Transcripción local con `base.en`, CPU y cuantización `int8`; no necesita GPU.
- Coincidencias entre la transcripción y las preguntas o variantes de la guía activa.
- Búsqueda manual por preguntas, palabras clave y tags.
- Controles para iniciar, pausar, reanudar y detener.
- Prueba de señal de audio y selección de dispositivos.
- Restauración de la última guía abierta correctamente.

La selección de una aplicación concreta no está implementada: se captura la salida completa. Si una aplicación reproduce por otra salida, ese audio queda fuera de la captura.

## Requisitos

- Python **3.10 o posterior**, con Tkinter, para ejecutar desde fuentes.
- Windows o Linux x86_64 con una sesión gráfica.
- Internet para instalar dependencias y descargar el modelo la primera vez.
- Espacio libre para el entorno, el modelo y, si compilás, los archivos del build.
- En Linux: biblioteca `libpulse` y PulseAudio o PipeWire con `pipewire-pulse` activo en la sesión del usuario. Tkinter necesita un escritorio compatible con X11/XWayland.

La transcripción actual está configurada en **inglés** (`base.en`). Las guías pueden contener títulos y preguntas en español o inglés; eso no cambia el idioma del reconocimiento de voz.

## Instalación en Windows

Desde PowerShell, con Python instalado:

```powershell
git clone https://github.com/imNazax/InterHelper.git
cd InterHelper
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

No hace falta activar el entorno virtual: estos comandos usan directamente su Python. Las dependencias de audio para Windows se seleccionan automáticamente al instalar `requirements.txt`.

Para abrirlo las próximas veces, desde la carpeta del proyecto:

```powershell
.\.venv\Scripts\python.exe main.py
```

## Instalación en Linux — BETA

En Fedora, prepará Python y Tkinter:

```bash
sudo dnf install python3 python3-pip python3-tkinter
```

Luego, desde una terminal de tu sesión gráfica:

```bash
git clone https://github.com/imNazax/InterHelper.git
cd InterHelper
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py
```

En otras distros, instalá los paquetes equivalentes para Python, venv, Tkinter y `libpulse` con su gestor de paquetes. Ejecutá la aplicación como tu usuario habitual; el servidor de audio pertenece a tu sesión.

Encontrás un paso a paso adicional en [LINUX.md](LINUX.md).

### Comprobar el audio en Linux

```bash
.venv/bin/python check_linux_audio.py --list
.venv/bin/python check_linux_audio.py
.venv/bin/python check_linux_audio.py --microphone
.venv/bin/python check_linux_audio.py --transcribe
```

El diagnóstico captura tres segundos. Para probar la salida, dejá voz reproduciéndose **dentro de Linux** mientras ejecutás el comando. Para el micrófono, hablá durante la prueba. `--device N` permite elegir un índice del listado.

## Primer uso

1. Presioná **Abrir guía** y elegí tu archivo. Podés empezar con [examples/guia.json](examples/guia.json).
2. Revisá la cantidad de preguntas y probá algunas búsquedas manuales.
3. Seleccioná **Speaker / Output Device** y comprobá la señal con **Test Interview Audio**.
4. Activá **Listen to microphone** solo si también querés transcribir tu micrófono.
5. Presioná **START**. La primera ejecución puede descargar el modelo.
6. Usá **PAUSE** para pausar o reanudar y **STOP** para detener.

Detené la captura antes de cambiar de guía. Si el archivo nuevo es inválido, se conserva el catálogo anterior. Para mejorar las coincidencias, agregá variantes de las preguntas en `aliases` dentro de una guía JSON.

## Preparar una guía

### PDF

Debe tener texto seleccionable. Se reconocen preguntas por su redacción y por los encabezados en negrita cuando están disponibles. Los PDF escaneados necesitan OCR previo; InterHelper no incluye OCR.

### DOCX

Usá preguntas como títulos y respuestas debajo. Se admiten distintos niveles de títulos, preguntas reconocibles por su redacción, preguntas en negrita y tablas de dos columnas con pregunta y respuesta.

### TXT

Guardá el archivo en UTF-8. Las etiquetas explícitas ayudan a separar cada entrada:

```text
Pregunta: How do you troubleshoot a technical problem?
Respuesta: I define the symptoms, collect evidence and test possible causes.
I document the solution when the problem is resolved.

Pregunta: How do you prioritize your work?
Respuesta: I consider impact, urgency and dependencies.
```

### JSON

Usá una lista con `question` y `answer`. Opcionalmente, agregá `aliases`, `tags` y `keywords` como listas de textos:

```json
[
  {
    "question": "How do you troubleshoot a technical problem?",
    "answer": "I define the symptoms, collect evidence and isolate the cause.",
    "aliases": ["What is your troubleshooting process?"],
    "tags": ["troubleshooting", "method"]
  }
]
```

### Tags adicionales

Podés crear un archivo junto a tu guía con el mismo nombre y extensión `.tags.json`. Para `Mi guia.pdf`, usá `Mi guia.tags.json`:

```json
{"How do you troubleshoot a technical problem?": ["support", "diagnosis"]}
```

La búsqueda manual considera preguntas, variantes, palabras clave y tags. El reconocimiento por audio compara las preguntas y sus variantes. Los tags de una guía no se importan a otra.

## Privacidad y funcionamiento local

El procesamiento de las guías, el reconocimiento de preguntas y la transcripción se ejecutan en tu equipo. La aplicación mantiene el audio en memoria y no crea archivos de grabación. El código imprime transcripciones y mensajes de diagnóstico en la terminal.

La descarga inicial del modelo y la instalación de dependencias requieren conexión. Después de preparar el modelo local, la transcripción puede funcionar sin Internet. Los paquetes Linux generados por el build incluyen `base.en`.

Las preferencias se guardan en `interhelper_settings.json` junto al código en Windows, y en `$XDG_CONFIG_HOME/interhelper/` o `~/.config/interhelper/` en Linux. Las guías personales, preferencias, entornos y modelos descargados no forman parte de este repositorio.

## Generar portable y AppImage en Linux

Desde la carpeta del proyecto, en Linux x86_64:

```bash
bash build_linux.sh
```

El build ejecuta las pruebas, descarga el modelo, genera el portable con PyInstaller y construye la AppImage. Los resultados quedan en:

| Archivo o carpeta | Contenido |
| --- | --- |
| `dist/InterHelper/` | Portable completo. Ejecutá `InterHelper` dentro de esa carpeta. |
| `dist/InterHelper-x86_64.AppImage` | Aplicación en un único archivo. |
| `dist/InterHelper-Linux-completo.zip` | AppImage, portable, fuentes, versiones de dependencias y checksum. |

Para ejecutar la AppImage generada:

```bash
chmod +x dist/InterHelper-x86_64.AppImage
./dist/InterHelper-x86_64.AppImage
```

Si falla el montaje con FUSE:

```bash
APPIMAGE_EXTRACT_AND_RUN=1 ./dist/InterHelper-x86_64.AppImage
```

Si el portable ya se generó y necesitás repetir solo el empaquetado:

```bash
bash build_linux.sh --package-only
```

El build usa enlaces físicos para evitar duplicar el portable al preparar el AppDir, y comprueba el espacio disponible antes de empaquetar. La AppImage y el ZIP final sí requieren capacidad adicional.

Más detalles en [EXPORTAR-LINUX.md](EXPORTAR-LINUX.md). El build publicado es para Linux; la ejecución desde fuentes también está disponible en Windows.

## Limitaciones actuales

- Linux está en BETA; falta ampliar las pruebas entre distribuciones y en equipos físicos.
- El micrófono en Linux no quedó validado por las limitaciones de la VM usada.
- La transcripción actual reconoce inglés.
- Los bloques de audio y el tiempo de procesamiento introducen demora; el rendimiento depende del CPU y del audio disponible.
- La coincidencia se basa en el texto de las preguntas y variantes. Las paráfrasis sin vocabulario compartido pueden necesitar un `alias`.
- La extracción depende de la estructura del documento. Revisá las preguntas importadas antes de usar la guía.
- No hay captura aislada por aplicación ni OCR de PDF escaneados.

## Pruebas

Con las dependencias instaladas:

```bash
python -m unittest -v test_audio_linux test_guias test_packaging
```

Usá el Python de tu entorno virtual. Las pruebas de interfaz necesitan Tkinter y una pantalla disponible. Las de audio usan dispositivos simulados y no sustituyen una prueba de captura real.

Los paquetes Linux agregan un chequeo del runtime, el modelo local, VAD y la lectura de un PDF real:

```bash
./dist/InterHelper/InterHelper --self-check
APPIMAGE_EXTRACT_AND_RUN=1 ./dist/InterHelper-x86_64.AppImage --self-check
```

## Estructura del proyecto

| Archivo | Función |
| --- | --- |
| `main.py` | Interfaz y coordinación de la aplicación. |
| `audio_capture.py` | Selección del backend según el sistema. |
| `audio_capture_windows.py` | Captura WASAPI en Windows. |
| `audio_capture_linux.py` | Captura PulseAudio/PipeWire en Linux. |
| `transcriber.py` | Transcripción local con faster-whisper. |
| `pdf_parser.py` | Importación de PDF, DOCX, TXT y JSON. |
| `matcher.py` | Coincidencias y búsqueda en la guía activa. |
| `app_paths.py` | Rutas de preferencias y modelo. |
| `packaging/` | Configuración de empaquetado y exportación. |
| `examples/` | Guía genérica de ejemplo para empezar. |

## Reportar problemas

Abrí un [issue](https://github.com/imNazax/InterHelper/issues) indicando sistema operativo, versión de Python, cómo ejecutaste el programa y el error de la terminal. En Linux, agregá si usás PulseAudio o PipeWire y una VM o un equipo físico. Evitá incluir guías personales o contenido privado de una conversación.
