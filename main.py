"""
main.py - InterHelper: Asistente visual y local para entrevistas.
"""
import os
import sys
import queue
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from pdf_parser import load_guide
from matcher import QuestionMatcher, normalize_text
from audio_capture import list_audio_devices, get_running_relevant_apps, AudioStreamRecorder, shutdown_audio
from transcriber import AudioTranscriber

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
from app_paths import settings_path
SETTINGS_PATH = settings_path()


def _apply_tags(items, path):
    """Optional tags belong only to the loaded document."""
    sidecar = os.path.splitext(os.fspath(path))[0] + '.tags.json'
    if not os.path.isfile(sidecar):
        return items
    with open(sidecar, encoding='utf-8-sig') as handle:
        custom = json.load(handle)
    if not isinstance(custom, dict) or any(
        not isinstance(v, list) or not all(isinstance(t, str) for t in v)
        for v in custom.values()
    ):
        raise ValueError('El archivo .tags.json debe asociar preguntas con listas de tags.')
    custom = {normalize_text(k): v for k, v in custom.items()}
    for item in items:
        item['tags'] = list(dict.fromkeys(item.get('tags', []) + custom.get(normalize_text(item['question']), [])))
    return items


class InterHelperApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("InterHelper — Interview Assistant")
        self.root.geometry("900;780".replace(";", "x"))
        self.root.minsize(750, 600)

        # Estado del sistema
        self.questions = []
        self.active_guide = None
        self.matcher = None
        self.audio_sources = {"speakers": [], "microphones": []}
        self.running_apps = []
        self.state = "STOPPED"  # STOPPED, LISTENING, PAUSED

        self.interview_recorder = None
        self.mic_recorder = None
        self.transcriber = AudioTranscriber()
        self.ui_queue = queue.Queue()
        self.test_recorder = None
        self.capture_source_display = "Entire Output Device"
        self.displayed_answer = None
        self.recent_transcripts = {"interview": "--", "microphone": "--"}

        self._build_ui()
        self._refresh_sources()
        self._restore_last_guide()
        self._poll_ui_events()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self):
        # 1. Barra superior / Estado
        top_frame = ttk.Frame(self.root, padding=8)
        top_frame.pack(fill=tk.X)

        title_lbl = ttk.Label(top_frame, text="InterHelper", font=("Helvetica", 16, "bold"))
        title_lbl.pack(side=tk.LEFT, padx=5)

        self.status_lbl = ttk.Label(top_frame, text="● STOPPED", font=("Helvetica", 12, "bold"), foreground="gray")
        self.status_lbl.pack(side=tk.RIGHT, padx=10)

        # 2. Archivo PDF de Guía
        pdf_frame = ttk.LabelFrame(self.root, text="Guía de preguntas (PDF / DOCX / JSON / TXT)", padding=6)
        pdf_frame.pack(fill=tk.X, padx=10, pady=3)

        self.pdf_path_var = tk.StringVar(value="")
        ttk.Entry(pdf_frame, textvariable=self.pdf_path_var, state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(pdf_frame, text="[ Abrir guía ]", command=self._select_pdf).pack(side=tk.LEFT, padx=5)
        self.pdf_info_lbl = ttk.Label(pdf_frame, text="0 preguntas cargadas")
        self.pdf_info_lbl.pack(side=tk.LEFT, padx=5)

        # 3. Configuración de Audio
        audio_frame = ttk.LabelFrame(self.root, text="Configuración de Audio", padding=6)
        audio_frame.pack(fill=tk.X, padx=10, pady=3)

        # Fuente del Entrevistador
        r1 = ttk.Frame(audio_frame)
        r1.pack(fill=tk.X, pady=2)
        ttk.Label(r1, text="Interview Audio Source:", width=22).pack(side=tk.LEFT)
        self.app_source_combo = ttk.Combobox(r1, state="readonly")
        self.app_source_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # Speaker / Dispositivo de salida
        r2 = ttk.Frame(audio_frame)
        r2.pack(fill=tk.X, pady=2)
        ttk.Label(r2, text="Speaker / Output Device:", width=22).pack(side=tk.LEFT)
        self.speaker_combo = ttk.Combobox(r2, state="readonly")
        self.speaker_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # Micrófono
        r3 = ttk.Frame(audio_frame)
        r3.pack(fill=tk.X, pady=2)
        ttk.Label(r3, text="Microphone:", width=22).pack(side=tk.LEFT)
        self.mic_combo = ttk.Combobox(r3, state="readonly")
        self.mic_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        self.listen_mic_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(r3, text="Listen to microphone", variable=self.listen_mic_var).pack(side=tk.LEFT, padx=5)

        # Controles de audio y tests
        r4 = ttk.Frame(audio_frame)
        r4.pack(fill=tk.X, pady=4)
        ttk.Button(r4, text="[ Refresh Audio Sources ]", command=self._refresh_sources).pack(side=tk.LEFT, padx=4)
        ttk.Button(r4, text="[ Test Interview Audio ]", command=self._test_interview_audio).pack(side=tk.LEFT, padx=4)
        ttk.Button(r4, text="[ Test Microphone ]", command=self._test_mic_audio).pack(side=tk.LEFT, padx=4)
        self.test_feedback_lbl = ttk.Label(r4, text="", foreground="blue")
        self.test_feedback_lbl.pack(side=tk.LEFT, padx=10)

        # 4. Botones de Control Principal
        ctrl_frame = ttk.Frame(self.root, padding=6)
        ctrl_frame.pack(fill=tk.X, padx=10, pady=2)

        self.start_btn = tk.Button(ctrl_frame, text="▶ START", bg="#2e7d32", fg="white", font=("Helvetica", 11, "bold"), padx=15, command=self.start)
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.pause_btn = tk.Button(ctrl_frame, text="⏸ PAUSE", bg="#f57f17", fg="white", font=("Helvetica", 11, "bold"), padx=15, state=tk.DISABLED, command=self.pause)
        self.pause_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = tk.Button(ctrl_frame, text="■ STOP", bg="#c62828", fg="white", font=("Helvetica", 11, "bold"), padx=15, state=tk.DISABLED, command=self.stop)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        # Búsqueda manual de respaldo
        search_frame = ttk.Frame(ctrl_frame)
        search_frame.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=10)
        ttk.Label(search_frame, text="Search question:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search_change)
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.root.bind("<Control-space>", lambda e: self.search_entry.focus_set())
        # INTERHELPER_TAGS_V1
        self.search_results = []
        self.search_list = tk.Listbox(self.root, height=3, exportselection=False)
        self.search_list.pack(fill=tk.X, padx=18, pady=2)
        self.search_list.bind('<<ListboxSelect>>', self._select_tag_result)
        self.search_entry.bind('<Return>', self._select_tag_result)
        self.search_entry.bind('<Escape>', lambda e: self.search_var.set(''))
        self.tags_lbl = ttk.Label(self.root, text='Buscá palabras de la guía o tags del documento | Esc: volver a detección', wraplength=850)
        self.tags_lbl.pack(fill=tk.X, padx=18)


        # 5. Visualización Principal: DETECTED QUESTION & YOUR ANSWER
        main_display = ttk.Frame(self.root, padding=8)
        main_display.pack(fill=tk.BOTH, expand=True, padx=10, pady=2)

        # Encabezado de Pregunta Detectada
        q_header = ttk.Frame(main_display)
        q_header.pack(fill=tk.X)
        ttk.Label(q_header, text="DETECTED QUESTION", font=("Helvetica", 10, "bold"), foreground="#1565c0").pack(side=tk.LEFT)
        self.match_meta_lbl = ttk.Label(q_header, text="Match: -- | Source: --", font=("Helvetica", 9), foreground="#555")
        self.match_meta_lbl.pack(side=tk.RIGHT)

        self.detected_q_lbl = ttk.Label(main_display, text="Waiting for interviewer question...", font=("Helvetica", 14, "bold"), wraplength=850, justify=tk.LEFT, foreground="#212121")
        self.detected_q_lbl.pack(fill=tk.X, pady=(2, 6))

        # Respuesta Preparada (Grande y legible)
        ttk.Label(main_display, text="YOUR ANSWER", font=("Helvetica", 11, "bold"), foreground="#2e7d32").pack(anchor=tk.W)
        answer_frame = ttk.Frame(main_display)
        answer_frame.pack(fill=tk.BOTH, expand=True, pady=(2, 6))
        self.answer_text = tk.Text(answer_frame, wrap=tk.WORD, font=("Helvetica", 15), bg="#fafafa", fg="#111", height=10, padx=10, pady=10)
        answer_scrollbar = ttk.Scrollbar(answer_frame, orient=tk.VERTICAL, command=self.answer_text.yview)
        self.answer_text.configure(yscrollcommand=answer_scrollbar.set)
        answer_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.answer_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 6. Transcripción reciente
        bottom_frame = ttk.LabelFrame(self.root, text="Recent Transcript", padding=4)
        bottom_frame.pack(fill=tk.X, padx=10, pady=4)
        self.transcript_lbl = ttk.Label(bottom_frame, text="APP: --\nMIC: --", font=("Consolas", 9), justify=tk.LEFT, foreground="#444", wraplength=820)
        self.transcript_lbl.pack(fill=tk.X)

    def _select_pdf(self):
        if self.state != 'STOPPED':
            messagebox.showwarning('Guía', 'Detené la captura antes de cambiar de guía.')
            return
        path = filedialog.askopenfilename(
            title='Abrir guía de preguntas',
            filetypes=[('Guías', '*.pdf *.docx *.json *.txt'), ('Word', '*.docx'),
                       ('PDF', '*.pdf'), ('Catálogo JSON', '*.json'), ('Texto', '*.txt')])
        if path:
            self._load_pdf(path)

    def _restore_last_guide(self):
        try:
            with open(SETTINGS_PATH, encoding='utf-8') as handle:
                path = json.load(handle).get('last_guide')
            if isinstance(path, str) and os.path.isfile(path):
                self._load_pdf(path)
        except (OSError, ValueError, AttributeError):
            pass

    def _load_pdf(self, path: str):
        if self.state != 'STOPPED':
            messagebox.showwarning('Guía', 'Detené la captura antes de cambiar de guía.')
            return False
        try:
            path = os.path.abspath(path)
            new_questions = _apply_tags(load_guide(path), path)
            new_matcher = QuestionMatcher(new_questions)
        except Exception as error:
            messagebox.showerror('Error al leer la guía', str(error))
            return False
        self.questions, self.matcher = new_questions, new_matcher
        self.active_guide = path
        self.displayed_answer = None
        while True:
            try:
                self.ui_queue.get_nowait()
            except queue.Empty:
                break
        self.search_var.set('')
        self.search_results = []
        self.search_list.delete(0, tk.END)
        self.detected_q_lbl.config(text='Waiting for interviewer question...')
        self.answer_text.delete('1.0', tk.END)
        self.tags_lbl.config(text='Buscá palabras de la guía o tags del documento')
        self.match_meta_lbl.config(text='Match: -- | Source: --')
        self.recent_transcripts = {'interview': '--', 'microphone': '--'}
        self.transcript_lbl.config(text='APP: --\nMIC: --')
        self.pdf_path_var.set(path)
        self.pdf_info_lbl.config(text=f'{len(self.questions)} preguntas cargadas')
        try:
            os.makedirs(os.path.dirname(os.path.abspath(SETTINGS_PATH)), exist_ok=True)
            temporary = SETTINGS_PATH + '.tmp'
            with open(temporary, 'w', encoding='utf-8') as handle:
                json.dump({'last_guide': path}, handle, ensure_ascii=False)
            os.replace(temporary, SETTINGS_PATH)
        except OSError as error:
            messagebox.showwarning('Preferencias', f'Guía cargada. No se pudo recordar su ubicación: {error}')
        return True

    def _refresh_sources(self):
        if self.state != "STOPPED" or self.test_recorder is not None:
            self.test_feedback_lbl.config(text="Detenga la captura antes de actualizar.")
            return
        try:
            self.audio_sources = list_audio_devices()
            self.running_apps = get_running_relevant_apps()

            # Opciones de fuente del entrevistador
            app_options = ["Entire Output Device"]
            self.app_source_combo["values"] = app_options
            if app_options:
                self.app_source_combo.current(0)

            # Speakers / Output
            spk_names = [f"{s['index']}: {s['name']}" for s in self.audio_sources["speakers"]]
            self.speaker_combo["values"] = spk_names
            if spk_names:
                self.speaker_combo.current(next((i for i, d in enumerate(self.audio_sources["speakers"]) if d.get("is_default")), 0))

            # Microphones
            mic_names = [f"{m['index']}: {m['name']}" for m in self.audio_sources["microphones"]]
            self.mic_combo["values"] = mic_names
            if mic_names:
                self.mic_combo.current(next((i for i, d in enumerate(self.audio_sources["microphones"]) if d.get("is_default")), 0))

            self.test_feedback_lbl.config(text="Fuentes actualizadas ✓")
        except Exception as e:
            self.audio_sources = {"speakers": [], "microphones": []}
            for combo in (self.speaker_combo, self.mic_combo):
                combo.set("")
                combo["values"] = []
            self.test_feedback_lbl.config(text="No se pudieron cargar las fuentes de audio.")
            messagebox.showerror("Audio", str(e))

    def _test_interview_audio(self):
        self._test_audio(self.speaker_combo, True)

    def _test_mic_audio(self):
        self._test_audio(self.mic_combo, False)

    def _test_audio(self, combo, loopback):
        if self.state != "STOPPED" or self.test_recorder is not None:
            self.test_feedback_lbl.config(text="Detenga la captura antes de probar.")
            return
        if not combo.get():
            self.test_feedback_lbl.config(text="Seleccione un dispositivo.")
            return
        recorder = AudioStreamRecorder(int(combo.get().split(":")[0]), loopback)
        self.test_recorder = recorder
        self.test_feedback_lbl.config(text="Probando señal real (3s)...")
        recorder.start()
        self.root.after(3500, lambda: self._finish_audio_test(recorder))

    def _finish_audio_test(self, recorder):
        recorder.stop()
        self.test_recorder = None
        if recorder.error:
            text = "Error: " + recorder.error
        elif recorder.peak_rms > 30:
            text = f"Audio detectado ✓ (RMS pico: {recorder.peak_rms:.0f})"
        else:
            text = "Sin señal. Reproduzca voz y compruebe la salida seleccionada."
        self.test_feedback_lbl.config(text=text)

    def start(self):
        if self.state != "STOPPED" or self.test_recorder is not None:
            return
        if not self.questions:
            messagebox.showwarning("Atención", "Abrí una guía de preguntas con el botón Abrir guía.")
            return

        spk_str = self.speaker_combo.get()
        if not spk_str:
            messagebox.showwarning("Atención", "Seleccione un dispositivo de salida / speaker.")
            return

        try:
            spk_idx = int(spk_str.split(":")[0])
        except ValueError:
            messagebox.showerror("Audio", "Selección de salida inválida.")
            return

        if any(r and r.thread and r.thread.is_alive() for r in (self.interview_recorder, self.mic_recorder)):
            messagebox.showwarning("Audio", "La captura anterior todavía está cerrando. Espere antes de iniciar.")
            return
        self.mic_recorder = None
        # Iniciar grabador de Interview (Loopback)
        self.interview_recorder = AudioStreamRecorder(device_index=spk_idx, is_loopback=True)
        self.interview_recorder.start()

        # Iniciar grabador de Micrófono si está habilitado
        mic_q = None
        if self.listen_mic_var.get() and self.mic_combo.get():
            try:
                mic_idx = int(self.mic_combo.get().split(":")[0])
                self.mic_recorder = AudioStreamRecorder(device_index=mic_idx, is_loopback=False)
                self.mic_recorder.start()
                mic_q = self.mic_recorder.audio_queue
            except Exception as e:
                print(f"[AUDIO] No se pudo iniciar mic: {e}")

        self.capture_source_display = "Entire Output Device — " + spk_str
        self.state = "STARTING"
        self._update_state_ui()
        self.test_feedback_lbl.config(text="Captura de salida completa; captura por aplicación no implementada.")
        self.root.after(100, self._finish_start)

    def _finish_start(self):
        if self.state != "STARTING":
            return
        recorders = [r for r in (self.interview_recorder, self.mic_recorder) if r]
        if not all(r.ready.is_set() for r in recorders):
            self.root.after(100, self._finish_start)
            return
        if self.interview_recorder.error or not self.interview_recorder.running:
            error = self.interview_recorder.error or "La captura se detuvo."
            self.stop()
            messagebox.showerror("Error de captura", error)
            return
        mic_q = None
        if self.mic_recorder:
            if self.mic_recorder.error:
                messagebox.showwarning("Micrófono", self.mic_recorder.error + "\nSe continúa solo con loopback.")
            else:
                mic_q = self.mic_recorder.audio_queue
        try:
            self.transcriber.start(
                interview_queue=self.interview_recorder.audio_queue,
                mic_queue=mic_q,
                on_transcript_cb=self._on_transcript_event
            )
        except Exception as exc:
            self.stop()
            messagebox.showerror("Transcripción", str(exc))
            return
        self.state = "LISTENING"
        self._update_state_ui()

    def pause(self):
        if self.state == "LISTENING":
            self.transcriber.pause()
            self.state = "PAUSED"
        elif self.state == "PAUSED":
            self.transcriber.resume()
            self.state = "LISTENING"
        self._update_state_ui()

    def stop(self):
        if self.transcriber:
            self.transcriber.stop()
        if self.interview_recorder:
            self.interview_recorder.stop()
        if self.mic_recorder:
            self.mic_recorder.stop()

        self.state = "STOPPED"
        self._update_state_ui()

    def _update_state_ui(self):
        if self.state == "STARTING":
            self.status_lbl.config(text="● STARTING", foreground="#f57f17")
            self.start_btn.config(state=tk.DISABLED)
            self.pause_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
        elif self.state == "LISTENING":
            self.status_lbl.config(text="● LISTENING", foreground="#2e7d32")
            self.start_btn.config(state=tk.DISABLED)
            self.pause_btn.config(state=tk.NORMAL, text="⏸ PAUSE")
            self.stop_btn.config(state=tk.NORMAL)
        elif self.state == "PAUSED":
            self.status_lbl.config(text="⏸ PAUSED", foreground="#f57f17")
            self.pause_btn.config(text="▶ RESUME")
        else:
            self.status_lbl.config(text="● STOPPED", foreground="gray")
            self.start_btn.config(state=tk.NORMAL)
            self.pause_btn.config(state=tk.DISABLED, text="⏸ PAUSE")
            self.stop_btn.config(state=tk.DISABLED)

    def _on_transcript_event(self, source: str, chunk_text: str, context_text: str):
        self.ui_queue.put(("transcript", (source, chunk_text)))
        if self.matcher:
            match_res = self.matcher.match(context_text, source=source)
            if match_res:
                item, score = match_res
                src_display = self.capture_source_display if source == "interview" else "Microphone"
                self.ui_queue.put(("match", (item, score, src_display)))

    def _poll_ui_events(self):
        while not self.ui_queue.empty():
            ev_type, data = self.ui_queue.get_nowait()
            if ev_type == "transcript":
                source, text = data
                self.recent_transcripts[source] = text[-260:]
                self.transcript_lbl.config(text=f"APP: {self.recent_transcripts['interview']}\nMIC: {self.recent_transcripts['microphone']}")
            elif ev_type == "match":
                if self.search_var.get().strip():
                    continue

                item, score, src_display = data
                if not any(item is question for question in self.questions):
                    continue
                self.detected_q_lbl.config(text=item["question"])
                self.tags_lbl.config(text="Tags: " + ", ".join(item.get("tags", [])))
                self.match_meta_lbl.config(text=f"Match: {score:.0f}% | Source: {src_display}")
                self._show_answer(item)

        if self.state in ("LISTENING", "PAUSED") and self.interview_recorder:
            if self.interview_recorder.error or not self.interview_recorder.running:
                error = self.interview_recorder.error or "La captura se detuvo."
                self.stop()
                messagebox.showerror("Error de captura", error)
            else:
                mic_level = self.mic_recorder.current_rms if self.mic_recorder else 0
                self.test_feedback_lbl.config(text=f"Salida completa RMS: {self.interview_recorder.current_rms:.0f} | Mic: {mic_level:.0f}")
        self.root.after(100, self._poll_ui_events)

    def _on_search_change(self, *args):
        from matcher import search_questions
        query = self.search_var.get()
        self.search_results = search_questions(query, self.questions)
        self.search_list.delete(0, tk.END)
        for item in self.search_results:
            self.search_list.insert(tk.END, item['question'])
        if self.search_results:
            self.search_list.selection_set(0)
            self._select_tag_result()
        elif query.strip():
            self.match_meta_lbl.config(text='Sin coincidencias para ese tag')

    def _select_tag_result(self, event=None):
        indices = self.search_list.curselection()
        if not indices or not self.search_results:
            return
        item = self.search_results[indices[0]]
        self.detected_q_lbl.config(text=item['question'])
        self.match_meta_lbl.config(text='Match: Manual | Source: Tags')
        self.tags_lbl.config(text='Tags: ' + ', '.join(item.get('tags', [])))
        if hasattr(self, '_show_answer'):
            self._show_answer(item)
        else:
            self.answer_text.delete('1.0', tk.END)
            self.answer_text.insert(tk.END, item['answer'])
            self.answer_text.yview_moveto(0)


    def _show_answer(self, item):
        value = (item["question"], item["answer"])
        if value == self.displayed_answer:
            return  # Keep scroll position while the same question is recognized.
        self.displayed_answer = value
        self.answer_text.delete("1.0", tk.END)
        self.answer_text.insert(tk.END, item["answer"])
        self.answer_text.yview_moveto(0)

    def on_close(self):
        self.stop()
        if self.test_recorder:
            self.test_recorder.stop()
        recorders = [r for r in (self.interview_recorder, self.mic_recorder, self.test_recorder) if r]
        if not any(r.thread and r.thread.is_alive() for r in recorders):
            shutdown_audio()
        self.root.destroy()
        sys.exit(0)

if __name__ == "__main__":
    if '--self-check' in sys.argv:
        # Validate the frozen runtime and local model without starting audio or Tk.
        from faster_whisper import WhisperModel
        from app_paths import model_source
        from faster_whisper.vad import get_vad_model
        import numpy as np
        model = WhisperModel(model_source(), device='cpu', compute_type='int8', local_files_only=True)
        list(model.transcribe(np.zeros(16000, dtype=np.float32), language='en', vad_filter=True)[0])
        get_vad_model()
        import ctypes
        ctypes.CDLL('libpulse.so.0')
        tk.Tcl()
        from pdf_parser import check_pdf_support
        check_pdf_support()
        print('InterHelper: Python, Tk, Whisper CPU, modelo local, VAD y lectura PDF OK.')
        sys.exit(0)
    root = tk.Tk()
    app = InterHelperApp(root)
    root.mainloop()
