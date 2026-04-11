---
name: audio-recording
description: Audio capture patterns for Windows — PyAudio mic, WASAPI loopback speaker, device detection
---

# Audio Recording Skill

## Microphone Recording (PyAudio Standard)
```python
import pyaudio
p = pyaudio.PyAudio()
stream = p.open(format=pyaudio.paInt16, channels=1, rate=44100,
               input=True, frames_per_buffer=1024)
frames = []
for _ in range(int(44100 / 1024 * duration_seconds)):
    frames.append(stream.read(1024, exception_on_overflow=False))
stream.stop_stream(); stream.close(); p.terminate()
```

## Speaker/System Audio (WASAPI Loopback)
Standard PyAudio CANNOT capture system audio. MUST use pyaudiowpatch.

```python
import pyaudiowpatch as pyaudio_wp

p = pyaudio_wp.PyAudio()
wasapi = p.get_host_api_info_by_type(pyaudio_wp.paWASAPI)
default_spk = p.get_device_info_by_index(wasapi['defaultOutputDevice'])

# Find loopback device matching default speaker
loopback = None
for lb in p.get_loopback_device_info_generator():
    if default_spk['name'] in lb['name']:
        loopback = lb
        break

# MUST use callback mode — blocking read() hangs when no audio plays
frames = []
def callback(in_data, frame_count, time_info, status):
    if in_data:
        frames.append(in_data)
    return (None, pyaudio_wp.paContinue)

stream = p.open(
    format=pyaudio_wp.paInt16,
    channels=loopback['maxInputChannels'],
    rate=int(loopback['defaultSampleRate']),
    input=True,
    input_device_index=loopback['index'],
    frames_per_buffer=512,
    stream_callback=callback,
)
# Wait for duration, then stop
time.sleep(duration)
stream.stop_stream(); stream.close(); p.terminate()
```

## Smart Device Detection
```python
# Scan all MME input devices, find one with actual audio
best_rms, best_device = 0, None
for i in range(p.get_device_count()):
    info = p.get_device_info_by_index(i)
    api = p.get_host_api_info_by_index(info['hostApi'])['name']
    if info['maxInputChannels'] > 0 and 'MME' in api:
        stream = p.open(format=pyaudio.paInt16, channels=1, rate=44100,
                       input=True, input_device_index=i, frames_per_buffer=1024)
        frames = [stream.read(1024) for _ in range(int(44100/1024))]  # 1 second
        stream.stop_stream(); stream.close()
        audio = np.frombuffer(b''.join(frames), dtype=np.int16)
        rms = int(np.sqrt(np.mean(audio.astype(float)**2)))
        if rms > best_rms:
            best_rms, best_device = rms, i
```

## Key Facts
- SteelSeries Sonar virtual devices: silent via PyAudio (use hardware mic instead)
- FxSound Audio Enhancer: breaks all loopback methods except pyaudiowpatch callback
- Loopback only captures frames when audio is actually playing
- Speaker sample rate often 48000Hz, mic 44100Hz — resample when merging
- Device hot-swap: recordmymeeting library checks every 2 seconds
- Separate files: microphone.wav (user), speaker.wav (interviewer), merged.wav, screen.mp4

## Audio Quality Check (RMS)
```python
import numpy as np
audio = np.frombuffer(b''.join(frames), dtype=np.int16)
rms = int(np.sqrt(np.mean(audio.astype(float)**2)))
# rms > 50 = speech detected
# rms > 10 = ambient noise (mic connected)
# rms = 0 = silent (virtual device or muted)
```
