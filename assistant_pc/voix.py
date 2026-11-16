"""Lecture à voix haute : le serveur découpe le texte en phrases et les synthétise (WAV), l'appli les joue.
La phrase suivante est synthétisée pendant que la précédente est jouée."""
import io
import threading
import wave
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal


def play_wav(data: bytes, stop: threading.Event):
    import sounddevice as sd
    with wave.open(io.BytesIO(data)) as w:
        rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        frames = w.readframes(w.getnframes())
    if width != 2:
        return
    step = 2048 * channels * width
    with sd.RawOutputStream(samplerate=rate, channels=channels, dtype="int16") as out:
        for i in range(0, len(frames), step):
            if stop.is_set():
                return
            out.write(frames[i:i + step])


class Speaker(QObject):
    speaking = Signal(bool)
    failed = Signal(str)

    def __init__(self, api_getter, voice_getter):
        super().__init__()
        self._api, self._voice = api_getter, voice_getter
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def say(self, text: str):
        """Lit le texte ; interrompt la lecture en cours."""
        self.stop()
        if not text.strip():
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(text, self._stop), daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self, text: str, stop: threading.Event):
        self.speaking.emit(True)
        try:
            api, voice = self._api(), self._voice()
            segments = [s for s in api.speech_segments(text) if s.strip()]
            with ThreadPoolExecutor(1) as pool:
                nxt = pool.submit(api.speech_audio, segments[0], voice) if segments else None
                for i in range(len(segments)):
                    if stop.is_set():
                        break
                    data = nxt.result()
                    nxt = pool.submit(api.speech_audio, segments[i + 1], voice) if i + 1 < len(segments) else None
                    play_wav(data, stop)
        except Exception as e:
            if not stop.is_set():
                self.failed.emit(f"Lecture à voix haute impossible : {e}")
        finally:
            self.speaking.emit(False)
