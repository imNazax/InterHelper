"""Local Whisper transcription with per-source context and chunk overlap."""
import threading
import queue
import time
import numpy as np
from typing import Optional
from app_paths import model_source

SILENCE_RMS = 0.001
OVERLAP_SECONDS = 0.35
SAMPLE_RATE = 16000


class AudioTranscriber:
    def __init__(self, model_size='base.en', language='en'):
        self.model_size, self.language = model_size, language
        self.model = None
        self.running = False
        self.paused = False
        self.thread: Optional[threading.Thread] = None
        self.context_window = []
        self.context_seconds = 12
        self._tails = {}
        self._stop_event = threading.Event()
        self.error = None

    def load_model(self):
        if self.model is None:
            from faster_whisper import WhisperModel
            print(f"[STT] Cargando modelo faster-whisper '{self.model_size}' (int8/CPU)...")
            self.model = WhisperModel(model_source(self.model_size), device='cpu', compute_type='int8')
            print('[STT] Modelo listo.')

    def start(self, interview_queue, mic_queue, on_transcript_cb):
        if self.thread and self.thread.is_alive():
            if self.running:
                return
            raise RuntimeError('Whisper todavía está terminando. Espere y vuelva a iniciar.')
        self.context_window.clear()
        self._tails.clear()
        self.error = None
        self.running, self.paused = True, False
        self._stop_event.clear()
        self.thread = threading.Thread(target=self._worker_loop,
                                      args=(interview_queue, mic_queue, on_transcript_cb), daemon=True)
        self.thread.start()

    def pause(self):
        self.paused = True

    def resume(self):
        self.context_window.clear()
        self._tails.clear()
        self.paused = False

    def stop(self):
        self.running = False
        self._stop_event.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=1)

    def _worker_loop(self, interview_q, mic_q, callback):
        try:
            self.load_model()
            while not self._stop_event.is_set():
                if self.paused:
                    # Discard paused audio rather than transcribing a backlog on resume.
                    for q in (interview_q, mic_q):
                        if q is not None:
                            while True:
                                try:
                                    q.get_nowait()
                                except queue.Empty:
                                    break
                    self._stop_event.wait(.1)
                    continue
                try:
                    chunk = interview_q.get(timeout=.1)
                    self._transcribe_chunk(chunk, 'interview', callback)
                except queue.Empty:
                    pass
                if mic_q is not None:
                    try:
                        self._transcribe_chunk(mic_q.get_nowait(), 'microphone', callback)
                    except queue.Empty:
                        pass
        except Exception as exc:
            self.error = str(exc)
            print(f'[STT] Error: {exc}')
        finally:
            self.running = False

    def _transcribe_chunk(self, audio_data, source, callback):
        if len(audio_data) == 0 or self.model is None or self._stop_event.is_set() or self.paused:
            return
        rms = float(np.sqrt(np.mean(audio_data ** 2)))
        if rms < SILENCE_RMS:
            self._tails.pop(source, None)
            return
        tail = self._tails.get(source)
        now = time.monotonic()
        if tail is not None and now - tail[0] < self.context_seconds:
            audio = np.concatenate((tail[1], audio_data))
        else:
            audio = audio_data
        self._tails[source] = (now, audio_data[-int(SAMPLE_RATE * OVERLAP_SECONDS):].copy())
        try:
            segments, _ = self.model.transcribe(audio, language=self.language,
                                                beam_size=1, vad_filter=True)
            text = ' '.join(s.text.strip() for s in segments).strip()
            if not text or self._stop_event.is_set() or self.paused:
                return
            now = time.monotonic()
            self.context_window = [x for x in self.context_window if x[0] >= now - self.context_seconds]
            previous = [x[2] for x in self.context_window if x[1] == source]
            # Remove repeated words introduced by the small audio overlap.
            if previous:
                prior, words = previous[-1].split(), text.split()
                for length in range(min(8, len(prior), len(words)), 0, -1):
                    if [w.lower().strip('.,?!') for w in prior[-length:]] == [w.lower().strip('.,?!') for w in words[:length]]:
                        text = ' '.join(words[length:])
                        break
            if not text:
                return
            self.context_window.append((now, source, text))
            # Newlines preserve fragment boundaries for newest-fragment-first matching.
            context = '\n'.join(x[2] for x in self.context_window if x[1] == source)
            print(f'[STT] {source}: {text}')
            callback(source, text, context)
        except Exception as exc:
            self.error = str(exc)
            print(f'[STT] Error transcribiendo audio: {exc}')
