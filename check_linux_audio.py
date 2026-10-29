"""Live Linux smoke check. Captures in memory; never writes audio to disk."""
import argparse
import queue
import sys
import numpy as np
from audio_capture import AudioStreamRecorder, list_audio_devices, shutdown_audio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true', help='List sources and exit')
    parser.add_argument('--device', type=int, help='Source index; defaults to the default device')
    parser.add_argument('--microphone', action='store_true', help='Test microphone instead of output capture')
    parser.add_argument('--transcribe', action='store_true', help='Transcribe one three-second block with base.en on CPU')
    args = parser.parse_args()
    recorder = None
    try:
        devices = list_audio_devices()
        for kind, entries in devices.items():
            for entry in entries:
                print(f"{kind}: {entry['index']}: {entry['name']}" + (' [default]' if entry['is_default'] else ''))
        if args.list:
            return 0
        sources = devices['microphones' if args.microphone else 'speakers']
        if not sources:
            raise RuntimeError('No hay micrófonos disponibles en la sesión.' if args.microphone else 'No hay salidas con monitor de audio disponibles.')
        index = args.device
        if index is None:
            index = next((s['index'] for s in sources if s['is_default']), sources[0]['index'])
        if index not in [s['index'] for s in sources]:
            raise ValueError('--device debe corresponder al tipo de fuente elegido (salida o --microphone).')
        model = None
        if args.transcribe:
            from faster_whisper import WhisperModel
            print('Cargando base.en en CPU. El primer uso necesita conexión para descargar el modelo.')
            model = WhisperModel('base.en', device='cpu', compute_type='int8')
        recorder = AudioStreamRecorder(index, is_loopback=not args.microphone)
        print('Hablá por el micrófono: se capturarán tres segundos.' if args.microphone else 'Reproducí voz por la salida seleccionada: se capturarán tres segundos.')
        recorder.start()
        if not recorder.ready.wait(10):
            raise RuntimeError('El servidor de audio no respondió al iniciar.')
        if recorder.error:
            raise RuntimeError(recorder.error)
        try:
            samples = recorder.audio_queue.get(timeout=15)
        except queue.Empty:
            raise RuntimeError(recorder.error or 'No llegaron muestras del dispositivo.')
        recorder.stop()
        print(f'Audio: {len(samples)} muestras mono a 16000 Hz; RMS={float(np.sqrt(np.mean(samples * samples))):.5f}')
        if recorder.peak_rms <= 30:
            raise RuntimeError('Captura abierta pero sin señal detectable. Revisá el volumen y la fuente seleccionada; en una VM, verificá que el dispositivo esté habilitado.')
        if model is not None:
            segments, _ = model.transcribe(samples, language='en', beam_size=1, vad_filter=True)
            print('Transcripción:', ' '.join(s.text.strip() for s in segments))
        return 0
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    finally:
        if recorder is not None:
            recorder.stop()
        shutdown_audio()


if __name__ == '__main__':
    raise SystemExit(main())
