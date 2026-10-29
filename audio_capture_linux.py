"""Capture output monitors and microphones via PulseAudio / pipewire-pulse."""
import importlib
import queue
import threading
import numpy as np

TARGET_SAMPLE_RATE = 16000
CAPTURE_RATE = 48000
_devices = {}
_device_lock = threading.RLock()


def _get_api():
    try:
        return importlib.import_module('soundcard')
    except (ImportError, OSError, AssertionError) as exc:
        raise RuntimeError('No se pudo conectar al audio de Linux. Instalá SoundCard y libpulse y verificá PulseAudio o PipeWire con pipewire-pulse en tu sesión.') from exc


def get_running_relevant_apps():
    return []


def list_audio_devices():
    api = _get_api()
    try:
        speakers = api.all_speakers()
        microphones = api.all_microphones(include_loopback=False)
        default_speaker = api.default_speaker() if speakers else None
        default_mic = api.default_microphone() if microphones else None
        entries, devices = {'speakers': [], 'microphones': []}, {}
        for speaker in speakers:
            # PulseAudio exposes the sink's capture source as <sink-id>.monitor.
            monitor = api.get_microphone(id=speaker.id + '.monitor', include_loopback=True)
            if not monitor.isloopback:
                raise RuntimeError('La salida no tiene un monitor de audio.')
            index = len(devices)
            devices[index] = (monitor.id, True)
            entries['speakers'].append({
                'index': index, 'name': speaker.name, 'rate': CAPTURE_RATE,
                'channels': monitor.channels,
                'is_default': bool(default_speaker and speaker.id == default_speaker.id),
            })
        for mic in microphones:
            index = len(devices)
            devices[index] = (mic.id, False)
            entries['microphones'].append({
                'index': index, 'name': mic.name, 'rate': CAPTURE_RATE,
                'channels': mic.channels,
                'is_default': bool(default_mic and mic.id == default_mic.id),
            })
        with _device_lock:
            _devices.clear()
            _devices.update(devices)
        return entries
    except Exception as exc:
        raise RuntimeError(f'No se pudieron enumerar las fuentes. Verificá PulseAudio o PipeWire con pipewire-pulse. Detalle: {exc}') from exc


def shutdown_audio():
    with _device_lock:
        _devices.clear()


def _to_mono_16k(samples):
    audio = np.asarray(samples, dtype=np.float32)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    # Low-pass before decimation to avoid aliasing into the speech band.
    taps = np.arange(63) - 31
    kernel = np.sinc(2 * (7200 / CAPTURE_RATE) * taps) * np.hamming(63)
    kernel /= kernel.sum()
    return np.convolve(audio, kernel, mode='same')[::3].astype(np.float32)


class AudioStreamRecorder:
    def __init__(self, device_index: int, is_loopback: bool = False):
        self.device_index = device_index
        self.is_loopback = is_loopback
        with _device_lock:
            self._device = _devices.get(device_index)
        self.running = False
        self.thread = None
        self.stream = None
        self.audio_queue = queue.Queue(maxsize=4)
        self.current_rms = self.peak_rms = 0.0
        self.error = None
        self.ready = threading.Event()
        self._stop_event = threading.Event()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.error = None
        self.ready.clear()
        self._stop_event.clear()
        self.running = True
        self.thread = threading.Thread(target=self._record_loop, daemon=True)
        self.thread.start()

    def _record_loop(self):
        try:
            if self._device is None:
                raise ValueError('Dispositivo desconocido. Actualizá las fuentes de audio.')
            device_id, loopback = self._device
            if loopback != self.is_loopback:
                raise ValueError('Seleccioná una salida para loopback o un micrófono para entrada.')
            mic = _get_api().get_microphone(id=device_id, include_loopback=loopback)
            if bool(mic.isloopback) != loopback:
                raise ValueError('La fuente cambió. Actualizá los dispositivos.')
            with mic.recorder(samplerate=CAPTURE_RATE, blocksize=4800) as stream:
                self.stream = stream
                self.ready.set()
                parts, frames = [], 0
                while not self._stop_event.is_set():
                    data = stream.record(numframes=4800)
                    if self._stop_event.is_set():
                        break
                    data = np.asarray(data, dtype=np.float32)
                    if not data.size:
                        continue
                    # Keep the Windows GUI's signed 16-bit RMS scale.
                    self.current_rms = float(np.sqrt(np.mean(data * data))) * 32768
                    self.peak_rms = max(self.peak_rms, self.current_rms)
                    parts.append(data)
                    frames += len(data)
                    if frames >= CAPTURE_RATE * 3:
                        audio = _to_mono_16k(np.concatenate(parts, axis=0))
                        parts, frames = [], 0
                        try:
                            self.audio_queue.put_nowait(audio)
                        except queue.Full:
                            try:
                                self.audio_queue.get_nowait()
                            except queue.Empty:
                                pass
                            self.audio_queue.put_nowait(audio)
        except Exception as exc:
            self.error = f'No se pudo capturar audio de Linux: {exc}'
        finally:
            self.stream = None
            self.running = False
            self.current_rms = 0.0
            self.ready.set()

    def stop(self):
        self._stop_event.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)
