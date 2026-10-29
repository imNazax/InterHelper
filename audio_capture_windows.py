"""WASAPI loopback and microphone capture. Audio stays in memory."""
import threading
import queue
import numpy as np
from typing import Optional
import pyaudiowpatch as pyaudio

try:
    import psutil
except ImportError:
    psutil = None

KNOWN_APPS = {
    'teams.exe': 'Microsoft Teams', 'ms-teams.exe': 'Microsoft Teams',
    'discord.exe': 'Discord', 'brave.exe': 'Brave',
    'chrome.exe': 'Google Chrome', 'firefox.exe': 'Mozilla Firefox',
}
TARGET_SAMPLE_RATE = 16000
_api_lock = threading.RLock()
_audio_api = None


def _get_api():
    global _audio_api
    # Call only while holding _api_lock. One lifecycle for the whole app.
    if _audio_api is None:
        _audio_api = pyaudio.PyAudio()
    return _audio_api


def shutdown_audio():
    global _audio_api
    with _api_lock:
        if _audio_api is not None:
            _audio_api.terminate()
            _audio_api = None


def get_running_relevant_apps():
    apps, seen = [], set()
    if psutil is None:
        return apps
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            name = proc.info['name'] or ''
            friendly = KNOWN_APPS.get(name.lower())
            if friendly and friendly not in seen:
                seen.add(friendly)
                apps.append({'name': friendly, 'exe': name, 'pid': proc.info['pid']})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return apps


def list_audio_devices():
    speakers, microphones = [], []
    with _api_lock:
        p = _get_api()
        wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_loopback = None
        try:
            default_loopback = int(p.get_default_wasapi_loopback()['index'])
        except (OSError, ValueError):
            pass
        default_mic = int(wasapi.get('defaultInputDevice', -1))
        for i in range(p.get_device_count()):
            dev = p.get_device_info_by_index(i)
            if int(dev['hostApi']) != int(wasapi['index']):
                continue
            channels = int(dev.get('maxInputChannels', 0))
            if channels <= 0:
                continue
            loopback = bool(dev.get('isLoopbackDevice', False))
            entry = {'index': i, 'name': dev['name'],
                     'rate': int(dev['defaultSampleRate']), 'channels': channels,
                     'is_default': i == (default_loopback if loopback else default_mic)}
            (speakers if loopback else microphones).append(entry)
    return {'speakers': speakers, 'microphones': microphones}


def resample_and_normalize(raw_data, in_rate, in_channels):
    audio = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0
    if in_channels > 1:
        audio = audio.reshape(-1, in_channels).mean(axis=1)
    if in_rate != TARGET_SAMPLE_RATE and audio.size:
        new_len = int(audio.size * TARGET_SAMPLE_RATE / in_rate)
        audio = np.interp(np.arange(new_len) * in_rate / TARGET_SAMPLE_RATE,
                          np.arange(audio.size), audio).astype(np.float32)
    return audio


class AudioStreamRecorder:
    def __init__(self, device_index: int, is_loopback: bool = False):
        self.device_index = device_index
        self.is_loopback = is_loopback
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.stream = None
        self.audio_queue = queue.Queue(maxsize=4)
        self.current_rms = 0.0
        self.peak_rms = 0.0
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
            with _api_lock:
                p = _get_api()
                dev = p.get_device_info_by_index(self.device_index)
                if self.is_loopback and not dev.get('isLoopbackDevice', False):
                    raise ValueError('Select a WASAPI device with [Loopback], not a regular output.')
                if not self.is_loopback and dev.get('isLoopbackDevice', False):
                    raise ValueError('Select a microphone, not a loopback device.')
                channels = int(dev.get('maxInputChannels', 0))
                if channels <= 0:
                    raise ValueError('Selected device has no input channels.')
                rate = int(dev['defaultSampleRate'])
                p.is_format_supported(rate, input_device=self.device_index,
                                      input_channels=channels, input_format=pyaudio.paInt16)
                self.stream = p.open(format=pyaudio.paInt16, channels=channels,
                                     rate=rate, input=True, input_device_index=self.device_index,
                                     frames_per_buffer=1024)
            print(f"[AUDIO] Capturing {dev['name']} (dev {self.device_index}, {channels} channels, {rate} Hz)")
            self.ready.set()
            parts, size = [], 0
            target = rate * channels * 2 * 3
            while not self._stop_event.is_set():
                data = self.stream.read(1024, exception_on_overflow=False)
                if not data:
                    continue
                arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                self.current_rms = float(np.sqrt(np.mean(arr * arr))) if arr.size else 0.0
                self.peak_rms = max(self.peak_rms, self.current_rms)
                parts.append(data)
                size += len(data)
                if size >= target:
                    processed = resample_and_normalize(b''.join(parts), rate, channels)
                    parts, size = [], 0
                    try:
                        self.audio_queue.put_nowait(processed)
                    except queue.Full:
                        try:
                            self.audio_queue.get_nowait()
                        except queue.Empty:
                            pass
                        self.audio_queue.put_nowait(processed)
        except Exception as exc:
            self.error = str(exc)
            print(f'[AUDIO] Error en stream (dev {self.device_index}): {exc}')
        finally:
            self.running = False
            self.ready.set()
            # Stream cleanup belongs to the recording thread, never the GUI.
            with _api_lock:
                if self.stream is not None:
                    try:
                        self.stream.stop_stream()
                    except Exception:
                        pass
                    try:
                        self.stream.close()
                    except Exception:
                        pass
                    self.stream = None
            self.current_rms = 0.0

    def stop(self):
        self._stop_event.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)
        # Do not terminate the shared PortAudio instance here.
