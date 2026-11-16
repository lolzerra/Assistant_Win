"""Dictée en direct, comme celle du site : le son est découpé en segments aux pauses ; le segment en cours
est retranscrit toutes les ~1,2 s (texte provisoire), les segments terminés sont figés.
La transcription est faite par le serveur (/api/transcribe, Whisper). Le son ne part que vers le serveur."""
import io
import math
import queue
import threading
import time
import wave
from array import array

from PySide6.QtCore import QObject, Signal

RATE = 16000
BLOCK = 320                 # 20 ms
PAUSE_BLOCKS = 40           # 0,8 s de silence termine un segment
MAX_BLOCKS = 25 * 50        # 25 s au plus par segment (Whisper travaille par 30 s)
MIN_SPEECH_BLOCKS = 20      # 0,4 s de voix au moins avant de transcrire
PREROLL_BLOCKS = 15         # 0,3 s gardées avant le début de la voix
REFRESH_S = 1.2             # retranscription du segment en cours
MIN_LEVEL = 100.0           # niveau RMS minimal d'une voix (sur 32768), sans gain automatique
_recording = 0              # ne pas relire la liste des micros pendant un enregistrement


# ---------- Micros ----------

def _host_api(sd) -> int:
    """API audio du micro par défaut (MME sous Windows) : accepte le 16 kHz et liste chaque micro une seule fois."""
    try:
        return sd.query_devices(kind="input")["hostapi"]
    except Exception:
        return 0


def microphones(refresh=True) -> list[str]:
    """Noms des micros disponibles. refresh relit la liste (micro branché depuis le lancement)."""
    import sounddevice as sd
    if refresh and not _recording:
        try:
            sd._terminate()
            sd._initialize()
        except Exception:
            pass
    api = _host_api(sd)
    names = []
    for d in sd.query_devices():
        if d["max_input_channels"] > 0 and d["hostapi"] == api and d["name"] not in names:
            names.append(d["name"])
    return names


def _device_index(sd, name: str):
    if not name:
        return None
    api = _host_api(sd)
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and d["hostapi"] == api and d["name"] == name:
            return i
    return False  # micro choisi introuvable


# ---------- Son ----------

def rms(block: bytes) -> float:
    samples = array("h", block)
    return math.sqrt(sum(x * x for x in samples) / max(1, len(samples)))


def level_of(value: float) -> int:
    """Niveau RMS → 0-100 sur une échelle en décibels (-60 dB → 0, 0 dB → 100)."""
    db = 20 * math.log10(max(value, 1) / 32768)
    return max(0, min(100, int((db + 60) * 100 / 60)))


class MicMonitor(QObject):
    """Écoute un micro sans rien envoyer, pour afficher son niveau (paramètres)."""
    level = Signal(int)
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self._stream = None

    def start(self, name: str):
        self.stop()
        try:
            import sounddevice as sd
            device = _device_index(sd, name)
            if device is False:
                self.failed.emit("Micro introuvable (débranché ?)")
                return
            emit = self.level.emit

            def callback(indata, frames, time_info, status):
                emit(level_of(rms(bytes(indata))))

            self._stream = sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16", device=device,
                                             blocksize=800, callback=callback)
            self._stream.start()
        except Exception as e:
            self._stream = None
            self.failed.emit(f"Micro inaccessible : {e}")

    def stop(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
            self.level.emit(0)


def to_wav(pcm: bytes) -> bytes:
    """WAV 16 kHz mono ; un micro faible est amplifié (jusqu'à ×8) pour Whisper."""
    samples = array("h", pcm)
    peak = max((abs(x) for x in samples), default=0)
    if 0 < peak < 16000:
        gain = min(8.0, 24000 / peak)
        samples = array("h", (max(-32767, min(32767, int(x * gain))) for x in samples))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(samples.tobytes())
    return buf.getvalue()


def join_text(a: str, b: str) -> str:
    if not a:
        return b
    if not b:
        return a
    if a[-1].isspace() or b[0] in " ,.!?…;:":
        return a + b
    return f"{a} {b}"


# ---------- Dictée ----------

class Dictation(QObject):
    update = Signal(str, str)   # texte figé, texte provisoire du segment en cours
    level = Signal(int)         # niveau du micro, 0 à 100
    failed = Signal(str)
    running = Signal(bool)      # le micro écoute
    finished = Signal()         # toutes les transcriptions sont arrivées

    def __init__(self, api_getter, context_getter, device_getter=lambda: ""):
        super().__init__()
        self._api = api_getter
        self._context = context_getter  # texte avant le curseur, pour guider la ponctuation
        self._device = device_getter
        self._stream = None
        self.active = False   # le micro écoute
        self.working = False  # transcriptions en cours (même après l'arrêt du micro)

    def start(self):
        if self.active or self.working:
            return
        try:
            import sounddevice as sd
        except (ImportError, OSError) as e:
            self.failed.emit(f"Micro indisponible : {e}")
            self.running.emit(False)
            return
        wanted = self._device()
        device = _device_index(sd, wanted)
        if device is False:
            try:
                microphones()
            except Exception:
                pass
            device = _device_index(sd, wanted)
        if device is False:
            self.failed.emit(f"Micro « {wanted} » introuvable : micro par défaut utilisé.")
            device = None

        self._audio: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._closed: list[bytes] = []      # segments terminés, à figer
        self._segment: list[bytes] = []     # segment en cours
        self._speech = 0
        self._dirty = False
        self._audio_done = threading.Event()
        self._cancel = threading.Event()
        audio = self._audio

        def callback(indata, frames, time_info, status):
            audio.put(bytes(indata))

        try:
            self._stream = sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16", device=device,
                                             blocksize=BLOCK, callback=callback)
            self._stream.start()
        except Exception as e:
            self._stream = None
            self.failed.emit("Impossible d'ouvrir le micro. Vérifiez qu'il est branché et que Windows autorise "
                             "les applications de bureau à l'utiliser (Paramètres → Confidentialité → Microphone).\n"
                             f"{e}")
            self.running.emit(False)
            return
        global _recording
        _recording += 1
        self.active = self.working = True
        self.running.emit(True)
        threading.Thread(target=self._listen, daemon=True).start()
        threading.Thread(target=self._pump, args=(self._context(),), daemon=True).start()

    def stop(self, flush=True):
        """flush : le segment en cours est encore transcrit ; sinon tout est abandonné."""
        if not self.active:
            if not flush and self.working:
                self._cancel.set()
            return
        global _recording
        _recording = max(0, _recording - 1)
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
        self._audio.put(None)
        self.running.emit(False)

    # ---------- Fil du son : découpage aux pauses ----------

    def _listen(self):
        try:
            self._listen_loop()
        except Exception as e:
            self.failed.emit(f"Dictée interrompue : {e}")
        finally:
            self._audio_done.set()

    def _listen_loop(self):
        preroll: list[bytes] = []
        noise = None
        calib: list[float] = []
        silence = 0
        n = 0
        while True:
            block = self._audio.get()
            if block is None:
                break
            lv = rms(block)
            n += 1
            if n % 2 == 0:  # 25 fois par seconde, pour l'onde
                self.level.emit(level_of(lv))
            if noise is None:  # 0,2 s pour mesurer le bruit de fond
                calib.append(lv)
                preroll.append(block)
                if len(calib) >= 10:
                    noise = sorted(calib)[len(calib) // 2]
                continue
            speaking = lv > max(MIN_LEVEL, noise * 2.5)
            if not speaking:
                noise = noise * 0.95 + lv * 0.05
            with self._lock:
                if self._segment:
                    self._segment.append(block)
                    if speaking:
                        self._speech += 1
                        silence = 0
                    else:
                        silence += 1
                    self._dirty = True
                    if silence >= PAUSE_BLOCKS or len(self._segment) >= MAX_BLOCKS:
                        self._close_segment()
                        silence = 0
                elif speaking:
                    self._segment = preroll + [block]
                    self._speech, silence = 1, 0
                    preroll = []
                else:
                    preroll = (preroll + [block])[-PREROLL_BLOCKS:]
        with self._lock:
            if not self._cancel.is_set():
                self._close_segment()
        self.level.emit(0)

    def _close_segment(self):  # sous self._lock
        if self._segment and self._speech >= MIN_SPEECH_BLOCKS:
            self._closed.append(b"".join(self._segment))
        self._segment, self._speech, self._dirty = [], 0, False

    # ---------- Fil des transcriptions : une requête à la fois ----------

    def _pump(self, context: str):
        committed, live = "", ""
        last_live = 0.0
        last_error = ""
        try:
            while not self._cancel.is_set():
                pcm, final = None, False
                with self._lock:
                    if self._closed:
                        pcm, final = self._closed.pop(0), True
                    elif (self._dirty and self._speech >= MIN_SPEECH_BLOCKS
                          and time.monotonic() - last_live >= REFRESH_S):
                        pcm, self._dirty = b"".join(self._segment), False
                        last_live = time.monotonic()
                if pcm is None:
                    if self._audio_done.is_set():
                        with self._lock:
                            if not self._closed:
                                break
                        continue
                    time.sleep(0.05)
                    continue
                try:
                    text = self._api().transcribe(to_wav(pcm), join_text(context, committed)[-300:]).strip()
                except Exception as e:
                    msg = f"Transcription impossible : {e}"
                    if msg != last_error:
                        self.failed.emit(msg)
                        last_error = msg
                    if e.__class__.__name__ in ("AuthError", "Unreachable"):
                        break
                    continue
                last_error = ""
                if self._cancel.is_set():
                    break
                if final:
                    committed, live = join_text(committed, text), ""
                else:
                    with self._lock:
                        if self._closed:  # le segment s'est fermé entre-temps : sa version figée arrive
                            continue
                    live = text
                self.update.emit(committed, live)
        finally:
            self.working = False
            self.finished.emit()
