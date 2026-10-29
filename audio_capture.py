"""Platform-specific audio backend with a shared public interface."""
import sys

if sys.platform == 'win32':
    from audio_capture_windows import (
        AudioStreamRecorder, list_audio_devices, get_running_relevant_apps,
        shutdown_audio, resample_and_normalize, TARGET_SAMPLE_RATE,
    )
elif sys.platform.startswith('linux'):
    from audio_capture_linux import (
        AudioStreamRecorder, list_audio_devices, get_running_relevant_apps,
        shutdown_audio, TARGET_SAMPLE_RATE,
    )
else:
    raise RuntimeError('InterHelper admite Windows y Linux.')
