"""Dictée : le micro est découpé en segments aux pauses, chaque segment est transcrit par le serveur
(/api/transcribe, Whisper) et le texte arrive au fur et à mesure. Le son ne part que vers le serveur."""
import io
import queue
import threading
import wave
from array import array

from PySide6.QtCore import QObject, Signal

RATE = 16000
BLOCK = 320                 # 20 ms
PAUSE_BLOCKS = 40           # 0,8 s de silence termine un segment
MAX_BLOCKS = 25 * 50        # 25 s au plus par segment (le serveur accepte ~2 min)
MIN_SPEECH_BLOCKS = 8       # moins de 160 ms de voix : bruit, ignoré
PREROLL_BLOCKS = 15         # 0,3 s gardées avant le début de la voix


def level(block: bytes) -> float:
    samples = array("h", block)
    return sum(abs(x) for x in samples) / max(1, len(samples))


def to_wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return buf.getvalue()


class Dictation(QObject):
    text = Signal(str)          # un segment transcrit
    failed = Signal(str)
    running = Signal(bool)
    busy = Signal(bool)         # une transcription est en cours

    def __init__(self, api_getter, context_getter):
        super().__init__()
        self._api = api_getter
        self._context = context_getter  # texte déjà présent, pour guider la ponctuation
        self._stream = None
        self._queue: queue.Queue = queue.Queue()
        self._cancel = threading.Event()
        self.active = False

    def start(self):
        if self.active:
            return
        try:
            import sounddevice as sd
        except (ImportError, OSError) as e:
            self.failed.emit(f"Micro indisponible : {e}")
            return
        self._queue = queue.Queue()
        self._cancel = threading.Event()
        q = self._queue

        def callback(indata, frames, time_info, status):
            q.put(bytes(indata))

        try:
            self._stream = sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16",
                                             blocksize=BLOCK, callback=callback)
            self._stream.start()
        except Exception as e:
            self._stream = None
            self.failed.emit("Impossible d'ouvrir le micro. Vérifiez qu'un micro est branché et que "
                             "Windows autorise les applications de bureau à l'utiliser "
                             f"(Paramètres → Confidentialité → Microphone).\n{e}")
            return
        self.active = True
        self.running.emit(True)
        threading.Thread(target=self._process, args=(q, self._cancel, self._context()), daemon=True).start()

    def stop(self, flush=True):
        """flush : le dernier segment est encore transcrit ; sinon il est abandonné."""
        if not self.active:
            return
        self.active = False
        if not flush:
            self._cancel.set()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._queue.put(None)
        self.running.emit(False)

    def _process(self, q: queue.Queue, cancel: threading.Event, context: str):
        segment: list[bytes] = []
        preroll: list[bytes] = []
        speech = silence = 0
        noise = 200.0
        said = context

        def close():
            nonlocal segment, speech, silence, said
            pcm, enough = b"".join(segment), speech >= MIN_SPEECH_BLOCKS
            segment, speech, silence = [], 0, 0
            if not enough or cancel.is_set():
                return
            self.busy.emit(True)
            try:
                text = self._api().transcribe(to_wav(pcm), said[-300:]).strip()
            except Exception as e:
                if not cancel.is_set():
                    self.failed.emit(f"Transcription impossible : {e}")
                text = ""
            finally:
                self.busy.emit(False)
            if text and not cancel.is_set():
                said = f"{said} {text}".strip()
                self.text.emit(text)

        while True:
            block = q.get()
            if block is None:
                break
            lv = level(block)
            loud = lv > max(400.0, noise * 3)
            if not loud:
                noise = noise * 0.95 + lv * 0.05  # bruit de fond, suivi lentement
            if segment:
                segment.append(block)
                if loud:
                    speech += 1
                    silence = 0
                else:
                    silence += 1
                if silence >= PAUSE_BLOCKS or len(segment) >= MAX_BLOCKS:
                    close()
            elif loud:
                segment = preroll + [block]
                speech, silence = 1, 0
                preroll = []
            else:
                preroll = (preroll + [block])[-PREROLL_BLOCKS:]
        if segment:
            close()
