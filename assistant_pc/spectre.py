"""Spectre du micro pour le visualiseur : graves à gauche, aigus à droite. FFT en Python pur (pas de numpy)."""
import cmath
import math

N = 512                      # 32 ms à 16 kHz, résolution 31 Hz
RATE = 16000
BANDS = 40
F_LOW, F_HIGH = 70.0, 7500.0
DB_FLOOR, DB_TOP = -75.0, -15.0

_bits = N.bit_length() - 1
_rev = [int(f"{i:0{_bits}b}"[::-1], 2) for i in range(N)]
_twiddles = [cmath.exp(-2j * math.pi * k / N) for k in range(N // 2)]
_window = [0.5 - 0.5 * math.cos(2 * math.pi * i / (N - 1)) for i in range(N)]  # Hann
_ref = (N / 4 * 32768) ** 2  # puissance d'une sinusoïde à pleine échelle (fenêtre de Hann)


def _edges() -> list[tuple[int, int, float]]:
    """Bandes réparties en échelle logarithmique : (premier bin, dernier bin exclu, correction en dB)."""
    out = []
    prev_hi = 1
    for i in range(BANDS):
        f0 = F_LOW * (F_HIGH / F_LOW) ** (i / BANDS)
        f1 = F_LOW * (F_HIGH / F_LOW) ** ((i + 1) / BANDS)
        lo = max(prev_hi if i else 1, round(f0 * N / RATE))
        lo = min(lo, N // 2 - 1)
        hi = max(lo + 1, round(f1 * N / RATE))
        prev_hi = hi
        centre = math.sqrt(f0 * f1)
        tilt = 3.0 * math.log2(centre / 500)  # la voix est plus forte dans les graves : +3 dB par octave
        out.append((lo, min(hi, N // 2), tilt))
    return out


_bands = _edges()


def _fft(x: list[complex]) -> list[complex]:
    a = [x[r] for r in _rev]
    size = 2
    while size <= N:
        half, step = size // 2, N // size
        for start in range(0, N, size):
            for k in range(half):
                t = _twiddles[k * step] * a[start + k + half]
                u = a[start + k]
                a[start + k] = u + t
                a[start + k + half] = u - t
        size *= 2
    return a


def spectrum(samples) -> list[int]:
    """N derniers échantillons int16 → BANDS niveaux de 0 à 100."""
    if len(samples) < N:
        return [0] * BANDS
    s = samples[-N:]
    spec = _fft([complex(s[i] * _window[i]) for i in range(N)])
    power = [abs(c) ** 2 for c in spec[: N // 2]]
    out = []
    for lo, hi, tilt in _bands:
        p = max(power[lo:hi]) / _ref
        db = 10 * math.log10(max(p, 1e-12)) + tilt
        out.append(max(0, min(100, int((db - DB_FLOOR) * 100 / (DB_TOP - DB_FLOOR)))))
    return out
