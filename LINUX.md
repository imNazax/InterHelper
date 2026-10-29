# Cómo ejecutar InterHelper en Linux

Estos pasos son para Linux x86_64. La versión se probó en Fedora 44 KDE.

## 1. Copiar el proyecto a Linux

Extraé el proyecto completo en una carpeta, por ejemplo `Descargas/InterHelper-Linux`.

Dentro deben estar `build_linux.sh`, `main.py`, `requirements.txt` y la carpeta `packaging`.

## 2. Abrir una terminal en esa carpeta

Desde el explorador de archivos, entrá a la carpeta del proyecto y elegí **Abrir terminal aquí**.

Todos los comandos siguientes se ejecutan en esa terminal, dentro de esa carpeta.

## 3. Preparar Fedora

Ejecutá una vez:

```bash
sudo dnf install python3 python3-pip python3-tkinter
```

Necesitás conexión a Internet y espacio libre para descargar las dependencias, el modelo y generar los paquetes. No ejecutes InterHelper ni el build con `sudo`.

## 4. Generar el programa

Ejecutá:

```bash
bash build_linux.sh
```

Esperá a que termine. El script prepara el entorno, instala las dependencias, descarga el modelo y genera el programa. No hace falta activar `.venv` manualmente.

Si aparece un error, resolvelo antes de continuar. Si dice **No queda espacio en el dispositivo**, liberá espacio en Linux y volvé a ejecutar el comando.

## 5. Abrir la AppImage

Cuando el build termine correctamente, ejecutá:

```bash
chmod +x dist/InterHelper-x86_64.AppImage
./dist/InterHelper-x86_64.AppImage
```

Si aparece un error relacionado con FUSE, usá:

```bash
APPIMAGE_EXTRACT_AND_RUN=1 ./dist/InterHelper-x86_64.AppImage
```

También podés ejecutar la carpeta portable:

```bash
./dist/InterHelper/InterHelper
```

## 6. Usar InterHelper

1. Presioná **Abrir guía** y elegí tu PDF, DOCX, JSON o TXT.
2. Comprobá que aparezca la cantidad de preguntas cargadas.
3. En **Speaker / Output Device**, elegí la salida por la que escuchás el audio.
4. Si el micrófono no funciona en la VM, desmarcá **Listen to microphone**. La captura de salida funciona sola.
5. Presioná **START** y reproducí voz en inglés dentro de Linux. Se captura todo lo que suena por la salida seleccionada.
6. Usá **PAUSE** para pausar o reanudar y **STOP** para detener.

El PDF debe tener texto seleccionable. La transcripción está configurada en inglés.

## 7. Abrirlo las próximas veces

No hace falta compilar otra vez. Abrí `dist/InterHelper-x86_64.AppImage`.

Podés copiar ese archivo a otra carpeta y ejecutarlo desde allí. Incluye Python, las dependencias y el modelo; no necesita conexión a Internet para funcionar.

Si recibís una AppImage ya generada, empezá por el paso 5, usando la ruta donde guardaste el archivo.

El archivo `dist/InterHelper-Linux-completo.zip` contiene la AppImage, el portable y las fuentes para guardar o trasladar todo junto.
