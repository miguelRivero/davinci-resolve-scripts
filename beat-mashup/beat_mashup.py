#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# resolve-menu: Utility
"""
Beat mashup para DaVinci Resolve
================================
Trocea al azar los vídeos de la carpeta (bin) que tengas abierta en el Media
Pool y los monta a ritmo sobre una canción: cada corte empieza y termina en un
beat y dura 1, 2 o 4 beats (los de 2 y 4 caen alineados con el compás). El BPM
lo indicas tú o se detecta del archivo de audio que haya en el pool.

Tu trabajo manual se conserva
  El script solo reescribe la pista de vídeo V1 y la de audio A1 de SU
  timeline (por defecto "Beat mashup"). Pon filtros y FX en adjustment clips,
  títulos u overlays en V2 o más arriba (y sonidos extra en A2+): al volver a
  generar se quedan como están. No pongas FX directamente en los cortes de
  V1, porque se rehacen cada vez.

Instalación
  Desde la raíz del repo: python tools/install.py
  (o copia este archivo a mano en
    %APPDATA%\\Blackmagic Design\\DaVinci Resolve\\Support\\Fusion\\Scripts\\Utility)
  y ejecútalo desde Workspace > Scripts > beat_mashup. Los mensajes salen en
  Workspace > Console.
  Necesita Python 3 de 64 bits instalado (python.org). Para detectar el BPM de
  MP3, M4A, AIFF... hace falta ffmpeg en el PATH (o su ruta en CONFIG); con
  WAV no hace falta. numpy es opcional: acelera el análisis.
"""
import math
import os
import random
import shutil
import subprocess
import sys
import time
import wave
from array import array

# --------------------------------------------------------------------------- ajustes
CONFIG = {
    'bpm': 0,                  # 0 = detectar del audio del pool
    'first_beat': None,        # segundos hasta el primer beat; None = detectar (0 si no hay audio)
    'bar_shift': None,         # 0-3: desplaza dónde empieza el compás; None = detectar
    'duration': 0,             # segundos; 0 = lo que dure la canción (60 s si no hay canción)
    'beat_weights': {1: 45, 2: 35, 4: 20},  # probabilidad relativa de cortes de 1, 2 y 4 beats
    'seed': None,              # None = aleatoria (se escribe en la consola y en un marcador)
    'timeline_name': 'Beat mashup',
    'audio_clip': '',          # nombre del clip de audio; '' = el primero que encuentre
    'include_subfolders': False,
    'markers_every_bars': 4,   # un marcador cada N compases (0 = ninguno)
    'avoid_reuse': True,       # intenta no repetir el mismo trozo de un vídeo
    'tempo_range': (70, 180),  # rango al detectar (evita que salga el doble o la mitad)
    'ffmpeg': '',              # ruta a ffmpeg.exe si no está en el PATH
    'show_dialog': True,       # ventana de opciones al ejecutar (si tu Resolve la admite)
}

TAG = 'beat-mashup'            # marca los marcadores que crea el script
SR = 11025                     # frecuencia de análisis
HOP = 256                      # muestras por paso de análisis (~23 ms)


# --------------------------------------------------------------------------- utilidades
def log(*args):
    print('[beat mashup]', *args)
    sys.stdout.flush()


def to_float(value, default=0.0):
    try:
        return float(str(value).strip().split()[0].replace(',', '.'))
    except (ValueError, IndexError):
        return default


def timecode_to_frames(tc, fps):
    try:
        parts = [int(p) for p in str(tc).replace(';', ':').split(':')]
        h, m, s, f = parts[-4:] if len(parts) >= 4 else [0] * (4 - len(parts)) + parts
        return int(((h * 60 + m) * 60 + s) * round(fps) + f)
    except ValueError:
        return 0


class Abort(Exception):
    pass


# --------------------------------------------------------------------------- acceso a Resolve
def get_resolve():
    g = globals()
    if g.get('resolve'):
        return g['resolve']
    for name in ('app', 'fusion', 'fu'):
        obj = g.get(name)
        if obj is not None:
            try:
                r = obj.GetResolve()
                if r:
                    return r
            except Exception:
                pass
    b = g.get('bmd')
    if b is not None:
        try:
            r = b.scriptapp('Resolve')
            if r:
                return r
        except Exception:
            pass
    try:
        import DaVinciResolveScript as dvr
        return dvr.scriptapp('Resolve')
    except ImportError:
        return None


class Clip:
    """A media pool item plus the properties the script needs."""

    def __init__(self, item):
        self.item = item
        try:
            p = item.GetClipProperty() or {}
        except Exception:
            p = {}
        self.props = p
        self.name = p.get('Clip Name') or (item.GetName() if hasattr(item, 'GetName') else '?')
        self.type = (p.get('Type') or '').lower()
        self.fps = to_float(p.get('FPS'), 0.0)
        self.frames = int(to_float(p.get('Frames'), 0))
        if not self.frames and p.get('Duration'):
            self.frames = timecode_to_frames(p['Duration'], self.fps or 25)
        self.path = p.get('File Path') or ''
        try:
            self.uid = item.GetUniqueId()
        except Exception:
            self.uid = self.name

    @property
    def is_video(self):
        t = self.type
        bad = ('timeline', 'compound', 'still', 'fusion', 'generator', 'multicam', 'title')
        return 'video' in t and not any(b in t for b in bad) and self.frames > 1

    @property
    def is_audio(self):
        return 'audio' in self.type and 'video' not in self.type and self.frames > 0

    def seconds(self, fallback_fps):
        return self.frames / (self.fps or fallback_fps)


def collect_clips(folder, recursive):
    out = []
    for item in folder.GetClipList() or []:
        out.append(Clip(item))
    if recursive:
        for sub in folder.GetSubFolderList() or []:
            out.extend(collect_clips(sub, True))
    return out


def find_timeline(project, name):
    for i in range(1, int(project.GetTimelineCount() or 0) + 1):
        tl = project.GetTimelineByIndex(i)
        if tl and tl.GetName() == name:
            return tl
    return None


# --------------------------------------------------------------------------- análisis de audio
def decode_mono(path, ffmpeg_hint=''):
    """Returns (samples as array('h'), sample rate)."""
    ffmpeg = ffmpeg_hint or shutil.which('ffmpeg') or shutil.which('ffmpeg.exe')
    if ffmpeg:
        flags = 0x08000000 if os.name == 'nt' else 0  # CREATE_NO_WINDOW
        proc = subprocess.run([ffmpeg, '-v', 'error', '-i', path, '-f', 's16le', '-ac', '1', '-ar', str(SR), '-'],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
        if proc.returncode == 0 and proc.stdout:
            a = array('h')
            a.frombytes(proc.stdout[: len(proc.stdout) // 2 * 2])
            if sys.byteorder == 'big':
                a.byteswap()
            return a, SR
        log('ffmpeg no pudo leer el audio:', proc.stderr.decode('utf-8', 'replace')[:300])
    if path.lower().endswith(('.wav', '.wave')):
        return read_wav(path)
    raise Abort('Para detectar el BPM de "%s" hace falta ffmpeg (o usa un WAV, o escribe el BPM).'
                % os.path.basename(path))


def read_wav(path):
    with wave.open(path, 'rb') as w:
        ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    step = max(1, int(round(rate / float(SR))))
    try:
        import numpy as np
        dt = {1: np.uint8, 2: np.int16, 4: np.int32}.get(width)
        if dt is None:  # 24-bit
            b = np.frombuffer(raw, np.uint8).reshape(-1, 3)
            x = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16))
            x = np.where(x >= 1 << 23, x - (1 << 24), x) >> 8
        else:
            x = np.frombuffer(raw, dt).astype(np.int64)
            if width == 1:
                x = (x - 128) << 8
            elif width == 4:
                x = x >> 16
        x = x.reshape(-1, ch).mean(1)[::step]
        return array('h', np.clip(x, -32768, 32767).astype(np.int16).tobytes()), rate / float(step)
    except ImportError:
        pass
    out = array('h')
    frame = ch * width
    for i in range(0, n, step):
        o = i * frame
        acc = 0
        for c in range(ch):
            q = o + c * width
            if width == 2:
                v = int.from_bytes(raw[q:q + 2], 'little', signed=True)
            elif width == 3:
                v = int.from_bytes(raw[q:q + 3], 'little', signed=True) >> 8
            elif width == 4:
                v = int.from_bytes(raw[q:q + 4], 'little', signed=True) >> 16
            else:
                v = (raw[q] - 128) << 8
            acc += v
        out.append(int(acc / ch))
    return out, rate / float(step)


def onset_envelope(x, sr):
    """Spectral-flux style novelty curves, one value per HOP samples:
    (all bands, low band only, envelope frames per second, latency in s)."""
    try:
        import numpy as np
        s = np.asarray(x, np.float32) / 32768.0
        n_fft = 1024
        if len(s) < n_fft * 4:
            raise Abort('El audio es demasiado corto para detectar el tempo.')
        win = np.hanning(n_fft).astype(np.float32)
        low_bins = max(2, int(150.0 * n_fft / sr))
        frames = 1 + (len(s) - n_fft) // HOP
        nov = np.zeros(frames, np.float32)
        low = np.zeros(frames, np.float32)
        prev = None
        for a in range(0, frames, 4096):
            b = min(frames, a + 4096)
            idx = np.arange(n_fft)[None, :] + HOP * np.arange(a, b)[:, None]
            mag = np.log1p(10 * np.abs(np.fft.rfft(s[idx] * win, axis=1)))
            full = mag if prev is None else np.vstack([prev, mag])
            d = np.maximum(0, np.diff(full, axis=0))
            lo = a + 1 if prev is None else a
            nov[lo:b] = d.sum(1)
            low[lo:b] = d[:, :low_bins].sum(1)
            prev = mag[-1:]
        return [float(v) for v in nov], [float(v) for v in low], sr / HOP, (n_fft / 2.0 + HOP / 2.0) / sr
    except ImportError:
        pass
    # pure Python: energy flux on the full band, a crude high band and a crude low band
    n = len(x) // HOP
    if n < 64:
        raise Abort('El audio es demasiado corto para detectar el tempo.')
    full, high, lowe = [0.0] * n, [0.0] * n, [0.0] * n
    prev, lp = 0, 0.0
    k = 1.0 / 16  # one-pole low-pass, ~110 Hz at 11 kHz
    for i in range(n):
        e = h = l = 0
        for v in x[i * HOP:(i + 1) * HOP]:
            e += v * v
            d = v - prev
            h += d * d
            prev = v
            lp += (v - lp) * k
            l += lp * lp
        full[i], high[i], lowe[i] = e, h, l

    def flux(band):
        m = (sum(band) / n) or 1.0
        lg = [math.log1p(10.0 * v / m) for v in band]
        return [0.0] + [max(0.0, lg[i] - lg[i - 1]) for i in range(1, n)]

    f1, f2, f3 = flux(full), flux(high), flux(lowe)
    return [a + b for a, b in zip(f1, f2)], f3, sr / HOP, (HOP / 2.0) / sr


def _smooth(v):
    n = len(v)
    return [0.25 * v[max(0, i - 1)] + 0.5 * v[i] + 0.25 * v[min(n - 1, i + 1)] for i in range(n)]


def _detrend(v, width):
    n, half = len(v), width // 2
    pre = [0.0]
    for x in v:
        pre.append(pre[-1] + x)
    out = []
    for i in range(n):
        a, b = max(0, i - half), min(n, i + half + 1)
        out.append(max(0.0, v[i] - (pre[b] - pre[a]) / (b - a)))
    return out


class Analysis:
    """Tempo + beat phase of a track (assumes a steady tempo)."""

    def __init__(self, path, tempo_range=(70, 180), ffmpeg=''):
        t0 = time.time()
        x, sr = decode_mono(path, ffmpeg)
        self.duration = len(x) / float(sr)
        nov, low, self.efps, self.latency = onset_envelope(x, sr)
        del x
        width = int(self.efps * 0.4)
        limit = int(self.efps * 480)  # the first 8 minutes are plenty
        self.nov = _smooth(_detrend(nov, width))[:limit] + [0.0, 0.0]
        self.low = _smooth(_detrend(low, width))[:limit] + [0.0, 0.0]
        self.tempo_range = tempo_range
        self.bpm = self._tempo()
        self.first_beat, self.bar_shift = self.phase_for(self.bpm)
        log('análisis: %.2f BPM, primer beat %.3f s, en %.1f s' % (self.bpm, self.first_beat, time.time() - t0))

    def _comb(self, bpm, step=0.5, curve=None):
        """best mean novelty on a beat grid of this tempo, and its phase (envelope frames)"""
        nov, P = (curve or self.nov), 60.0 / bpm * self.efps
        nb = int((len(nov) - 3) / P)
        if nb < 4:
            return 0.0, 0.0
        best, best_ph, ph = -1.0, 0.0, 0.0
        while ph < P:
            s, pos = 0.0, ph
            for _ in range(nb):
                i = int(pos)
                f = pos - i
                s += nov[i] + (nov[i + 1] - nov[i]) * f
                pos += P
            if s > best:
                best, best_ph = s, ph
            ph += step
        return best / nb, best_ph

    def _tempo(self):
        nov, efps = self.nov, self.efps
        lo, hi = self.tempo_range
        n = len(nov)
        mean = sum(nov) / n
        x = [v - mean for v in nov]
        best, best_bpm = -1e30, 120.0
        for lag in range(max(2, int(60.0 * efps / hi)), int(60.0 * efps / lo) + 2):
            ac = sum(x[i] * x[i + lag] for i in range(n - lag)) / (n - lag)
            bpm = 60.0 * efps / lag
            prior = math.exp(-0.5 * (math.log(bpm / 120.0, 2) / 0.9) ** 2)
            if lo <= bpm <= hi and ac * prior > best:
                best, best_bpm = ac * prior, bpm
        # refine: coarse then fine search on the beat-grid fit
        cands = [best_bpm * (0.96 + 0.08 * i / 80.0) for i in range(81)]
        bpm = max(cands, key=lambda b: self._comb(b)[0])
        cands = [bpm - 0.15 + 0.01 * i for i in range(31)]
        bpm = max(cands, key=lambda b: self._comb(b, 0.25)[0])
        # most tracks sit on a whole number: snap when that fits as well
        whole = float(round(bpm))
        if abs(whole - bpm) < 0.08 and self._comb(whole, 0.25)[0] >= 0.985 * self._comb(bpm, 0.25)[0]:
            bpm = whole
        # half / double tempo: a faster reading is plausible when the beats in between carry kicks or
        # bass as strongly; among plausible readings take the one nearest 120 BPM
        cands = sorted(c for c in (bpm / 2, bpm, bpm * 2) if lo <= c <= hi) or [bpm]
        base = self._comb(cands[0], 0.25, self.low)[0] or 1e-9
        plausible = [c for c in cands if self._comb(c, 0.25, self.low)[0] >= 0.85 * base]
        bpm = min(plausible, key=lambda c: abs(math.log(c / 120.0, 2)))
        return round(bpm, 2)

    def phase_for(self, bpm):
        """(seconds to the first beat, bar shift) for a given tempo"""
        score, ph = self._comb(bpm, 0.1)
        P = 60.0 / bpm * self.efps
        first = ph / self.efps + self.latency
        beat = 60.0 / bpm
        while first < 0:
            first += beat
        while first >= beat:
            first -= beat
        # downbeat guess: the beat of the bar with the most low-end (kick / bass) attack
        nov = self.low
        sums = [0.0] * 4
        k, pos = 0, ph
        while pos < len(nov) - 2:
            i = int(pos)
            sums[k % 4] += nov[i]
            k += 1
            pos += P
        j = max(range(4), key=lambda q: sums[q])
        return first, (4 - j) % 4


# --------------------------------------------------------------------------- plan de cortes
def plan_bounds(duration, bpm, first_beat, bar_shift, weights, rng, fps):
    """Cut times in seconds: 0, ..., duration. Every cut after the intro lands on a beat."""
    beat = 60.0 / bpm
    t0 = first_beat % beat
    bounds = [0.0]
    if t0 * fps >= 2:          # a short intro before the first beat
        bounds.append(t0)
    k = 0
    lengths = sorted(L for L, w in weights.items() if w > 0) or [1]
    while t0 + k * beat < duration - 1e-6:
        pos = (k + bar_shift) % 4
        allowed = [L for L in lengths if pos % L == 0]
        if not allowed:        # e.g. only 4-beat cuts but we're mid-bar: go to the next downbeat
            L = (4 - pos) % 4 or 4
        else:
            total = sum(weights[L] for L in allowed)
            r = rng.random() * total
            L = allowed[-1]
            for cand in allowed:
                r -= weights[cand]
                if r < 0:
                    L = cand
                    break
        k += L
        bounds.append(min(duration, t0 + k * beat))
    return bounds


def pick_clip(clips, need_tl, tl_fps, prev_uid, rng):
    def need_src(c):
        return max(1, int(round(need_tl * (c.fps or tl_fps) / tl_fps)))
    fit = [c for c in clips if c.frames >= need_src(c)]
    pool = [c for c in fit if c.uid != prev_uid] or fit
    if not pool:
        return max(clips, key=lambda c: c.seconds(tl_fps)), None
    c = pool[rng.randrange(len(pool))]
    return c, need_src(c)


def pick_start(clip, need, used, rng, avoid_reuse):
    span = clip.frames - need
    if span <= 0:
        return 0
    taken = used.setdefault(clip.uid, [])
    best, best_overlap = None, None
    for _ in range(16 if avoid_reuse else 1):
        s = rng.randint(0, span)
        overlap = sum(max(0, min(s + need, b) - max(s, a)) for a, b in taken)
        if best is None or overlap < best_overlap:
            best, best_overlap = s, overlap
        if overlap == 0:
            break
    taken.append((best, best + need))
    return best


# --------------------------------------------------------------------------- diálogo (opcional)
def get_ui(resolve):
    g = globals()
    fu = g.get('fu') or g.get('fusion')
    if fu is None:
        try:
            fu = resolve.Fusion()
        except Exception:
            fu = None
    b = g.get('bmd')
    if fu is None or b is None or not hasattr(b, 'UIDispatcher'):
        return None, None
    try:
        ui = fu.UIManager
        return ui, b.UIDispatcher(ui)
    except Exception:
        return None, None


def ask_options(ui, disp, cfg, info):
    """Returns updated cfg, or None if cancelled."""
    w = cfg['beat_weights']

    def row(label, widget):
        return ui.HGroup({'Weight': 0}, [ui.Label({'Text': label, 'Weight': 0.55}), widget])

    win = disp.AddWindow({'ID': 'BeatMashup', 'WindowTitle': 'Beat mashup', 'Geometry': [300, 200, 430, 470]}, [
        ui.VGroup({'Spacing': 6}, [
            ui.Label({'Text': info, 'WordWrap': True, 'Weight': 0}),
            ui.VGap(4),
            row('BPM (0 = detectar)', ui.DoubleSpinBox({'ID': 'bpm', 'Minimum': 0, 'Maximum': 400, 'Decimals': 2,
                                                         'Value': float(cfg['bpm'] or 0), 'Weight': 0.45})),
            row('Primer beat en s (-1 = detectar)', ui.DoubleSpinBox({
                'ID': 'first', 'Minimum': -1, 'Maximum': 60, 'Decimals': 3, 'SingleStep': 0.01,
                'Value': -1.0 if cfg['first_beat'] is None else float(cfg['first_beat']), 'Weight': 0.45})),
            row('Desplazar compás (-1 = detectar)', ui.SpinBox({
                'ID': 'shift', 'Minimum': -1, 'Maximum': 3,
                'Value': -1 if cfg['bar_shift'] is None else int(cfg['bar_shift']), 'Weight': 0.45})),
            row('Duración en s (0 = canción)', ui.DoubleSpinBox({'ID': 'dur', 'Minimum': 0, 'Maximum': 36000,
                                                                  'Decimals': 1, 'Value': float(cfg['duration'] or 0),
                                                                  'Weight': 0.45})),
            row('Peso cortes de 1 beat', ui.SpinBox({'ID': 'w1', 'Minimum': 0, 'Maximum': 100, 'Value': int(w.get(1, 0)), 'Weight': 0.45})),
            row('Peso cortes de 2 beats', ui.SpinBox({'ID': 'w2', 'Minimum': 0, 'Maximum': 100, 'Value': int(w.get(2, 0)), 'Weight': 0.45})),
            row('Peso cortes de 4 beats', ui.SpinBox({'ID': 'w4', 'Minimum': 0, 'Maximum': 100, 'Value': int(w.get(4, 0)), 'Weight': 0.45})),
            row('Semilla (vacío = aleatoria)', ui.LineEdit({'ID': 'seed', 'Text': '' if cfg['seed'] is None else str(cfg['seed']), 'Weight': 0.45})),
            row('Marcador cada N compases', ui.SpinBox({'ID': 'marks', 'Minimum': 0, 'Maximum': 64, 'Value': int(cfg['markers_every_bars']), 'Weight': 0.45})),
            row('Timeline', ui.LineEdit({'ID': 'name', 'Text': cfg['timeline_name'], 'Weight': 0.45})),
            ui.CheckBox({'ID': 'reuse', 'Text': 'Evitar repetir el mismo trozo de un vídeo', 'Checked': bool(cfg['avoid_reuse']), 'Weight': 0}),
            ui.Label({'Text': 'Solo se rehacen V1 y A1. Pon tus FX en V2 o más arriba.', 'WordWrap': True, 'Weight': 0}),
            ui.HGroup({'Weight': 0}, [ui.Button({'ID': 'cancel', 'Text': 'Cancelar'}),
                                      ui.Button({'ID': 'ok', 'Text': 'Generar', 'Default': True})]),
        ]),
    ])
    items = win.GetItems()
    result = {'ok': False}

    def done(ev, ok=False):
        result['ok'] = ok
        disp.ExitLoop()

    win.On.ok.Clicked = lambda ev: done(ev, True)
    win.On.cancel.Clicked = done
    win.On.BeatMashup.Close = done
    win.Show()
    disp.RunLoop()
    win.Hide()
    if not result['ok']:
        return None
    out = dict(cfg)
    out['bpm'] = float(items['bpm'].Value)
    first = float(items['first'].Value)
    out['first_beat'] = None if first < 0 else first
    shift = int(items['shift'].Value)
    out['bar_shift'] = None if shift < 0 else shift
    out['duration'] = float(items['dur'].Value)
    out['beat_weights'] = {1: int(items['w1'].Value), 2: int(items['w2'].Value), 4: int(items['w4'].Value)}
    seed = str(items['seed'].Text).strip()
    out['seed'] = int(seed) if seed.lstrip('-').isdigit() else (seed or None)
    out['markers_every_bars'] = int(items['marks'].Value)
    out['timeline_name'] = str(items['name'].Text).strip() or cfg['timeline_name']
    out['avoid_reuse'] = bool(items['reuse'].Checked)
    return out


def show_message(ui, disp, title, text):
    if ui is None:
        return
    try:
        win = disp.AddWindow({'ID': 'BeatMsg', 'WindowTitle': title, 'Geometry': [340, 260, 420, 180]}, [
            ui.VGroup([ui.Label({'Text': text, 'WordWrap': True}),
                       ui.Button({'ID': 'ok', 'Text': 'OK', 'Weight': 0})]),
        ])
        win.On.ok.Clicked = lambda ev: disp.ExitLoop()
        win.On.BeatMsg.Close = lambda ev: disp.ExitLoop()
        win.Show()
        disp.RunLoop()
        win.Hide()
    except Exception:
        pass


# --------------------------------------------------------------------------- montaje
def build(resolve, cfg, ui=None, disp=None):
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        raise Abort('No hay ningún proyecto abierto.')
    pool = project.GetMediaPool()
    folder = pool.GetCurrentFolder() or pool.GetRootFolder()
    folder_name = folder.GetName()

    clips = collect_clips(folder, cfg['include_subfolders'])
    videos = sorted([c for c in clips if c.is_video], key=lambda c: (c.name, c.uid))
    audios = [c for c in clips if c.is_audio]
    if not audios:  # the song can live anywhere in the pool
        audios = [c for c in collect_clips(pool.GetRootFolder(), True) if c.is_audio]
    if cfg['audio_clip']:
        audios = [c for c in audios if c.name == cfg['audio_clip']] or audios
    song = audios[0] if audios else None

    info = 'Carpeta "%s": %d vídeo(s). Canción: %s' % (folder_name, len(videos), song.name if song else 'ninguna')
    if ui is not None and cfg.get('show_dialog'):
        cfg = ask_options(ui, disp, cfg, info)
        if cfg is None:
            log('cancelado')
            return None
    log(info)
    if not videos:
        raise Abort('No hay vídeos en la carpeta "%s" del Media Pool. Abre la carpeta con tus clips y vuelve a ejecutar.'
                    % folder_name)
    if not any(w > 0 for w in cfg['beat_weights'].values()):
        raise Abort('Todos los pesos de corte son 0.')

    # ---- tempo
    bpm = float(cfg['bpm'] or 0)
    analysis = None
    if song and (bpm <= 0 or cfg['first_beat'] is None or cfg['bar_shift'] is None):
        if not song.path or not os.path.exists(song.path):
            if bpm <= 0:
                raise Abort('No encuentro el archivo de "%s" en disco para detectar el BPM.' % song.name)
        else:
            log('analizando', song.name, '...')
            analysis = Analysis(song.path, tuple(cfg['tempo_range']), cfg['ffmpeg'])
    if bpm <= 0:
        if not analysis:
            raise Abort('Indica el BPM o añade la canción al Media Pool para detectarlo.')
        bpm = analysis.bpm
    first_beat, bar_shift = 0.0, 0
    if analysis:
        first_beat, bar_shift = analysis.phase_for(bpm)
    if cfg['first_beat'] is not None:
        first_beat = float(cfg['first_beat'])
    if cfg['bar_shift'] is not None:
        bar_shift = int(cfg['bar_shift']) % 4

    # ---- timeline (only V1 and A1 are ours)
    name = cfg['timeline_name']
    tl = find_timeline(project, name)
    if tl:
        markers = tl.GetMarkers() or {}
        ours = [f for f, m in markers.items() if str(m.get('customData', '')).startswith(TAG)]
        v1 = tl.GetItemListInTrack('video', 1) or []
        a1 = tl.GetItemListInTrack('audio', 1) or []
        if (v1 or a1) and not ours:
            raise Abort('Ya existe un timeline "%s" que no ha creado este script. Cambia el nombre en las opciones '
                        'para no tocarlo.' % name)
        project.SetCurrentTimeline(tl)
        if v1 or a1:
            if not tl.DeleteClips(list(v1) + list(a1), False):
                raise Abort('No pude borrar los cortes anteriores de V1/A1 (¿pista bloqueada?).')
        for f in ours:
            tl.DeleteMarkerAtFrame(f)
        log('regenerando V1 y A1 de "%s"; el resto de pistas no se toca' % name)
    else:
        tl = pool.CreateEmptyTimeline(name)
        if not tl:
            raise Abort('No pude crear el timeline "%s".' % name)
        project.SetCurrentTimeline(tl)
        log('timeline nuevo "%s"' % name)

    fps = to_float(tl.GetSetting('timelineFrameRate'), 0) or to_float(project.GetSetting('timelineFrameRate'), 25)
    start = int(tl.GetStartFrame())

    if cfg['duration'] and cfg['duration'] > 0:
        duration = float(cfg['duration'])
    elif song:
        duration = analysis.duration if analysis else song.seconds(fps)
    else:
        duration = 60.0

    seed = cfg['seed'] if cfg['seed'] is not None else random.randrange(1, 10 ** 6)
    rng = random.Random(seed)
    bounds = plan_bounds(duration, bpm, first_beat, bar_shift, cfg['beat_weights'], rng, fps)
    grid = [int(round(b * fps)) for b in bounds]
    log('%.2f BPM, primer beat %.3f s, desplazamiento de compás %d, %d cortes, %.1f s, semilla %s'
        % (bpm, first_beat, bar_shift, len(bounds) - 1, duration, seed))

    # ---- song on A1
    song_items = []
    if song:
        song_fps = song.fps or fps
        n = max(1, min(song.frames, int(round(duration * song_fps))))
        got = pool.AppendToTimeline([{'mediaPoolItem': song.item, 'startFrame': 0, 'endFrame': n - 1,
                                      'mediaType': 2, 'trackIndex': 1, 'recordFrame': start}])
        if not got:
            log('aviso: no pude poner la canción en A1')
        song_items = list(got or [])

    # ---- cuts on V1, each placed where the previous one really ended
    rec, prev, used, placed, end_adjust, calibrated = start, None, {}, 0, 0, False
    t0 = time.time()
    for i in range(len(grid) - 1):
        need_tl = start + grid[i + 1] - rec
        if need_tl <= 0:
            continue
        clip, need = pick_clip(videos, need_tl, fps, prev, rng)
        if need is None:  # nothing long enough: use the whole longest clip
            need = clip.frames
        s = pick_start(clip, need, used, rng, cfg['avoid_reuse'])
        e = s + need - 1 + end_adjust
        got = pool.AppendToTimeline([{'mediaPoolItem': clip.item, 'startFrame': s, 'endFrame': e,
                                      'mediaType': 1, 'trackIndex': 1, 'recordFrame': rec}])
        if not got:
            raise Abort('Resolve no aceptó el corte %d (%s, frames %d-%d).' % (i + 1, clip.name, s, e))
        item = got[0]
        at, dur = int(item.GetStart()), int(item.GetDuration())
        if placed == 0 and at != rec:
            tl.DeleteClips([item] + song_items, False)
            raise Abort('Tu versión de Resolve ignora "recordFrame" al añadir clips; hace falta una versión '
                        'más reciente para este script.')
        if not calibrated and abs((clip.fps or fps) - fps) < 1e-3:
            calibrated = True
            if dur == need - 1 + end_adjust:
                end_adjust = 1  # this Resolve treats endFrame as exclusive
        rec = at + dur
        prev = clip.uid
        placed += 1
        if placed % 50 == 0:
            log('%d cortes...' % placed)

    # ---- markers
    info_note = '%.2f BPM · primer beat %.3f s · compás +%d · semilla %s · %d cortes' % (
        bpm, first_beat, bar_shift, seed, placed)
    tl.AddMarker(0, 'Cream', 'Beat mashup', info_note, 1, TAG + ':info')
    every = int(cfg['markers_every_bars'] or 0)
    if every > 0:
        beat = 60.0 / bpm
        t, k = first_beat % beat, 0
        bar = 0
        while t + k * beat < duration:
            if (k + bar_shift) % 4 == 0:
                if bar % every == 0:
                    f = int(round((t + k * beat) * fps))
                    if f > 0:
                        tl.AddMarker(f, 'Sky', 'Compás %d' % (bar + 1), '', 1, TAG + ':bar')
                bar += 1
            k += 1

    msg = ('%d cortes a %.2f BPM en "%s" (semilla %s, %.1f s).\nTus FX en V2+ se han conservado.'
           % (placed, bpm, name, seed, time.time() - t0))
    log(msg.replace('\n', ' '))
    return {'timeline': tl, 'bpm': bpm, 'first_beat': first_beat, 'bar_shift': bar_shift, 'seed': seed,
            'cuts': placed, 'grid': grid, 'start': start, 'fps': fps, 'message': msg}


def main():
    resolve = get_resolve()
    if resolve is None:
        log('No encuentro Resolve. Ejecuta el script desde Workspace > Scripts dentro de DaVinci Resolve.')
        return
    ui, disp = get_ui(resolve) if CONFIG.get('show_dialog') else (None, None)
    try:
        res = build(resolve, dict(CONFIG), ui, disp)
        if res:
            show_message(ui, disp, 'Beat mashup', res['message'])
    except Abort as e:
        log('ERROR:', e)
        show_message(ui, disp, 'Beat mashup', str(e))


if __name__ == '__main__' or 'resolve' in globals() or 'app' in globals():
    main()
