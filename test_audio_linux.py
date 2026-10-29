"""Linux backend contract tests; no audio server or hardware required."""
import queue
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import audio_capture_linux as audio
import app_paths


class FakeStream:
    def __init__(self, blocks=30, fail=False):
        self.blocks = blocks
        self.fail = fail
        self.finished = threading.Event()
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def record(self, numframes):
        if self.fail:
            raise OSError('device disconnected')
        if self.blocks:
            self.blocks -= 1
            return np.full((numframes, 2), 0.25, dtype=np.float32)
        self.finished.wait(0.01)
        return np.empty((0, 2), dtype=np.float32)


class LinuxAudioTests(unittest.TestCase):
    def setUp(self):
        self.stream = FakeStream()
        self.monitor = SimpleNamespace(id='output.monitor', name='Monitor', channels=2, isloopback=True,
                                       recorder=lambda **kwargs: self.stream)
        self.mic = SimpleNamespace(id='mic', name='Microphone', channels=1, isloopback=False,
                                   recorder=lambda **kwargs: self.stream)
        self.speaker = SimpleNamespace(id='output', name='Speakers')
        self.api = SimpleNamespace(
            all_speakers=lambda: [self.speaker],
            all_microphones=lambda **kwargs: [self.mic],
            default_speaker=lambda: self.speaker,
            default_microphone=lambda: self.mic,
            get_microphone=self.get_microphone,
        )
        self.patcher = patch.object(audio, '_get_api', return_value=self.api)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        audio.shutdown_audio()
        audio.list_audio_devices()

    def get_microphone(self, id, include_loopback=False):
        # PulseAudio source IDs differ from sink IDs; no fuzzy matching here.
        sources = [self.mic] + ([self.monitor] if include_loopback else [])
        for source in sources:
            if source.id == id:
                return source
        raise IndexError(f'no soundcard with id {id}')

    def recorder(self, index=0, loopback=True):
        r = audio.AudioStreamRecorder(index, loopback)
        self.addCleanup(r.stop)
        return r

    def test_lists_default_output_monitor_and_separate_microphone(self):
        devices = audio.list_audio_devices()
        self.assertTrue(devices['speakers'][0]['is_default'])
        self.assertTrue(devices['microphones'][0]['is_default'])
        self.assertNotEqual(devices['speakers'][0]['index'], devices['microphones'][0]['index'])
        self.assertEqual(audio._devices[0], ('output.monitor', True))
        self.assertEqual(devices['speakers'][0]['channels'], 2)
        self.assertEqual(devices['microphones'][0]['channels'], 1)

    def test_no_microphone_does_not_prevent_output_capture(self):
        self.api.all_microphones = lambda **kwargs: []
        self.api.default_microphone = lambda: (_ for _ in ()).throw(IndexError('no default source'))
        devices = audio.list_audio_devices()
        self.assertEqual(devices['microphones'], [])
        self.assertEqual(len(devices['speakers']), 1)

    def test_microphone_only_session_can_be_listed(self):
        self.api.all_speakers = lambda: []
        self.api.default_speaker = lambda: (_ for _ in ()).throw(IndexError('no default sink'))
        devices = audio.list_audio_devices()
        self.assertEqual(devices['speakers'], [])
        self.assertEqual(len(devices['microphones']), 1)

    def test_diagnostic_can_capture_microphone(self):
        import contextlib
        import importlib.util
        import io
        from pathlib import Path
        import sys
        spec = importlib.util.spec_from_file_location('diagnostic_under_test', Path(__file__).with_name('check_linux_audio.py'))
        diagnostic = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'audio_capture': audio}):
            spec.loader.exec_module(diagnostic)
        output = io.StringIO()
        with patch.object(sys, 'argv', ['check_linux_audio.py', '--microphone']), contextlib.redirect_stdout(output):
            self.assertEqual(diagnostic.main(), 0)
        self.assertIn('48000 muestras mono', output.getvalue())
        self.assertTrue(self.stream.closed)

    def test_output_capture_delivers_three_seconds_mono_16k_and_closes(self):
        r = self.recorder()
        r.start()
        self.assertTrue(r.ready.wait(2))
        samples = r.audio_queue.get(timeout=3)
        self.assertEqual(samples.shape, (48000,))
        self.assertEqual(samples.dtype, np.float32)
        self.assertAlmostEqual(float(samples[100:-100].mean()), 0.25, places=5)
        self.assertAlmostEqual(r.peak_rms, 8192, places=2)
        r.stop()
        self.assertFalse(r.thread.is_alive())
        self.assertTrue(self.stream.closed)
        self.assertIsNone(r.error)

    def test_microphone_capture(self):
        r = self.recorder(1, False)
        r.start()
        self.assertEqual(r.audio_queue.get(timeout=3).shape, (48000,))
        r.stop()
        self.assertIsNone(r.error)

    def test_unknown_device_reports_error_and_signals_ready(self):
        r = self.recorder(42)
        r.start()
        self.assertTrue(r.ready.wait(2))
        r.stop()
        self.assertIn('desconocido', r.error)
        self.assertFalse(r.running)

    def test_wrong_source_type_is_rejected(self):
        r = self.recorder(1, True)
        r.start()
        self.assertTrue(r.ready.wait(2))
        r.stop()
        self.assertIn('Seleccioná', r.error)

    def test_device_disconnect_closes_stream_and_reports_error(self):
        self.stream.fail = True
        r = self.recorder()
        r.start()
        self.assertTrue(r.ready.wait(2))
        r.stop()
        self.assertIn('disconnected', r.error)
        self.assertTrue(self.stream.closed)
        self.assertFalse(r.running)

    def test_queue_retains_latest_chunks_when_consumer_is_slow(self):
        self.stream.blocks = 180
        r = self.recorder()
        r.start()
        self.assertTrue(r.ready.wait(2))
        # Wait for all six chunks without consuming them.
        for _ in range(300):
            if self.stream.blocks == 0:
                break
            threading.Event().wait(0.01)
        r.stop()
        self.assertEqual(r.audio_queue.qsize(), 4)
        self.assertIsNone(r.error)

    def test_recorder_retains_device_identity_after_refresh(self):
        r = self.recorder()
        audio._devices[0] = ('other.monitor', True)
        self.assertEqual(r._device[0], 'output.monitor')

    def test_missing_server_is_actionable(self):
        self.api.all_speakers = lambda: (_ for _ in ()).throw(OSError('connection refused'))
        with self.assertRaisesRegex(RuntimeError, 'pipewire-pulse'):
            audio.list_audio_devices()

    def test_stereo_downmix(self):
        data = np.column_stack((np.ones(48000), -np.ones(48000)))
        self.assertTrue(np.allclose(audio._to_mono_16k(data), 0))

    def test_decimation_suppresses_out_of_band_tones(self):
        t = np.arange(48000) / 48000
        low = audio._to_mono_16k(np.sin(2 * np.pi * 1000 * t))[100:-100]
        high = audio._to_mono_16k(np.sin(2 * np.pi * 12000 * t))[100:-100]
        self.assertLess(float(np.std(high)), float(np.std(low)) * 0.02)


class SettingsTests(unittest.TestCase):
    def test_linux_uses_xdg_config(self):
        from pathlib import Path
        with patch.object(app_paths.sys, 'platform', 'linux'), patch.dict(app_paths.os.environ, {'XDG_CONFIG_HOME': str(Path.cwd())}):
            self.assertEqual(app_paths.settings_path(), str(Path.cwd() / 'interhelper' / 'interhelper_settings.json'))

    def test_relative_xdg_is_ignored(self):
        from pathlib import Path
        with patch.object(app_paths.sys, 'platform', 'linux'), patch.dict(app_paths.os.environ, {'XDG_CONFIG_HOME': 'relative'}):
            self.assertEqual(app_paths.settings_path(), str(Path.home() / '.config' / 'interhelper' / 'interhelper_settings.json'))


if __name__ == '__main__':
    unittest.main()
