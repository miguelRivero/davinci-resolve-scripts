#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# resolve-menu: Utility
"""
Beat mashup for DaVinci Resolve
===============================
Randomly slices videos from the Media Pool bin you have open and cuts them to
a song: each cut starts and ends on a beat and lasts between min_beats and
max_beats beats (valid values 1, 2, 4 – anything that divides evenly into a
bar). You type the BPM or it is detected from audio in the pool.

Optionally the script snaps each cut point to the nearest loud transient
(snare, clap, kick hit) within a half-beat window so that cuts align to the
loudest hits rather than the mathematical beat position.

All settings live in beat_mashup.cfg next to this file. Create or edit that
file to change behaviour without touching the code.  The script runs fine
without the file; built-in defaults are used.

Manual work is kept
  The script only rewrites video track V1 and audio track A1 of ITS timeline
  (default "Beat mashup"). Put filters and FX on adjustment clips, titles, or
  overlays on V2 or above (and extra sound on A2+): they stay when you
  regenerate. Do not put FX on the V1 cuts; those are rebuilt every run.

Install
  From this repository's root: python tools/install.py
  (or copy this file by hand to
    %APPDATA%\\Blackmagic Design\\DaVinci Resolve\\Support\\Fusion\\Scripts\\Utility)
  then run it from Workspace > Scripts > beat_mashup. Messages go to
  Workspace > Console.
  Needs 64-bit Python 3 (python.org). Detecting BPM from MP3, M4A, FLAC,
  AIFF, OGG... needs ffmpeg on PATH (or its path in the config file); WAV
  does not. numpy is optional and speeds up analysis.
"""
import configparser
import math
import os
import random
import shutil
import subprocess
import sys
import time
import wave
from array import array

# --------------------------------------------------------------------------- settings
CONFIG = {
    'bpm': 0,                  # 0 = detect from pool audio
    'first_beat': None,        # seconds to first beat; None = detect (0 if no audio)
    'bar_shift': None,         # 0-3: shift where the bar starts; None = detect
    'duration': 0,             # seconds; 0 = song length (60 s if no song)
    # Cut length range. Allowed beat counts are 1, 2, and 4 (the ones that
    # divide evenly into a 4/4 bar). min_beats and max_beats are inclusive;
    # any allowed count within the range gets equal probability.
    # e.g. min_beats=1 max_beats=4  → 1, 2, and 4-beat cuts (equal weight)
    #      min_beats=2 max_beats=4  → 2 and 4-beat cuts only
    #      min_beats=4 max_beats=4  → every cut is exactly one bar
    'min_beats': 1,
    'max_beats': 4,
    # Transient (hit) snapping ------------------------------------------------
    # When snap_to_hits is true, each computed beat boundary is shifted to the
    # nearest loud transient within a half-beat window.  Only boundaries where
    # the strongest nearby onset exceeds hit_threshold (0–1, fraction of the
    # loudest onset in the whole track) are moved; quieter beats stay put.
    'snap_to_hits': True,
    'hit_threshold': 0.35,     # 0 = snap everything, 1 = snap nothing
    # -------------------------------------------------------------------------
    'seed': None,              # None = random (written to the Console and a marker)
    'timeline_name': 'Beat mashup',
    'audio_clip': '',          # audio clip name; '' = first one found
    'include_subfolders': False,
    'markers_every_bars': 4,   # a marker every N bars (0 = none)
    'avoid_reuse': True,       # try not to reuse the same stretch of a video
    'tempo_range': (70, 180),  # range when detecting (avoids half/double tempo)
    'ffmpeg': '',              # path to ffmpeg.exe if it is not on PATH
    'show_dialog': True,       # options window when run (if this Resolve build supports it)
}

TAG = 'beat-mashup'            # tags markers this script creates
SR = 11025                     # analysis sample rate
HOP = 256                      # samples per analysis hop (~23 ms)

# --------------------------------------------------------------------------- config file
def _script_dir():
    """Directory that contains this .py file (works inside Resolve too)."""
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        return os.getcwd()


def load_config(cfg):
    """Read beat_mashup.cfg next to the script and merge into cfg dict."""
    path = os.path.join(_script_dir(), 'beat_mashup.cfg')
    if not os.path.exists(path):
        return cfg
    parser = configparser.ConfigParser(inline_comment_prefixes=('#', ';'))
    try:
        parser.read(path, encoding='utf-8')
    except Exception as e:
        log('Could not read beat_mashup.cfg:', e)
        return cfg
    if not parser.has_section('beat_mashup'):
        return cfg
    sec = parser['beat_mashup']
    out = dict(cfg)

    def _float(key, default):
        try:
            return float(sec[key])
        except (KeyError, ValueError):
            return default

    def _int(key, default):
        try:
            return int(sec[key])
        except (KeyError, ValueError):
            return default

    def _bool(key, default):
        try:
            return sec.getboolean(key)
        except (KeyError, ValueError):
            return default

    def _str(key, default):
        return sec.get(key, default)

    out['bpm'] = _float('bpm', cfg['bpm'])
    raw_first = _float('first_beat', -999)
    if raw_first != -999:
        out['first_beat'] = None if raw_first < 0 else raw_first
    raw_shift = _int('bar_shift', -999)
    if raw_shift != -999:
        out['bar_shift'] = None if raw_shift < 0 else raw_shift
    out['duration'] = _float('duration', cfg['duration'])
    out['min_beats'] = max(1, _int('min_beats', cfg['min_beats']))
    out['max_beats'] = max(1, _int('max_beats', cfg['max_beats']))
    out['snap_to_hits'] = _bool('snap_to_hits', cfg['snap_to_hits'])
    out['hit_threshold'] = max(0.0, min(1.0, _float('hit_threshold', cfg['hit_threshold'])))
    out['seed_raw'] = _str('seed', '')  # handled below
    seed_str = _str('seed', '').strip()
    if seed_str:
        out['seed'] = int(seed_str) if seed_str.lstrip('-').isdigit() else seed_str
    out['timeline_name'] = _str('timeline_name', cfg['timeline_name']).strip() or cfg['timeline_name']
    out['audio_clip'] = _str('audio_clip', cfg['audio_clip'])
    out['include_subfolders'] = _bool('include_subfolders', cfg['include_subfolders'])
    out['markers_every_bars'] = _int('markers_every_bars', cfg['markers_every_bars'])
    out['avoid_reuse'] = _bool('avoid_reuse', cfg['avoid_reuse'])
    out['ffmpeg'] = _str('ffmpeg', cfg['ffmpeg'])
    raw_range = _str('tempo_range', '').strip()
    if raw_range:
        try:
            lo, hi = [float(x.strip()) for x in raw_range.split(',')]
            out['tempo_range'] = (lo, hi)
        except ValueError:
            pass
    return out


# --------------------------------------------------------------------------- helpers
def log(*args):
    print('[beat mashup]', *args)
    flush = getattr(sys.stdout, 'flush', None)
    if callable(flush):
        try:
            flush()
        except Exception:
            pass


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


# --------------------------------------------------------------------------- Resolve access
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


# --------------------------------------------------------------------------- audio analysis
def find_ffmpeg(hint=''):
    if hint and os.path.exists(hint):
        return hint
    for candidate in (
        hint,
        shutil.which('ffmpeg'),
        shutil.which('ffmpeg.exe'),
        '/opt/homebrew/bin/ffmpeg',
        '/usr/local/bin/ffmpeg',
        os.path.expanduser('~/bin/ffmpeg'),
    ):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def decode_mono(path, ffmpeg_hint=''):
    """Returns (samples as array('h'), sample rate).

    Supported formats
    -----------------
    Without ffmpeg : WAV (any bit depth, any sample rate, mono or stereo)
    With ffmpeg    : MP3, FLAC, M4A/AAC, AIFF, OGG/Vorbis, OPUS, WMA, and
                     any other container/codec ffmpeg understands.

    If ffmpeg is not found and the file is not a WAV the function raises
    Abort with a message that explains what to install.
    """
    ffmpeg = find_ffmpeg(ffmpeg_hint)
    if ffmpeg:
        flags = 0x08000000 if os.name == 'nt' else 0  # CREATE_NO_WINDOW
        proc = subprocess.run(
            [ffmpeg, '-v', 'error', '-i', path,
             '-f', 's16le', '-ac', '1', '-ar', str(SR), '-'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
        if proc.returncode == 0 and proc.stdout:
            a = array('h')
            a.frombytes(proc.stdout[: len(proc.stdout) // 2 * 2])
            if sys.byteorder == 'big':
                a.byteswap()
            return a, SR
        log('ffmpeg could not read the audio:', proc.stderr.decode('utf-8', 'replace')[:300])
    # No ffmpeg — fall back to the built-in WAV reader
    if path.lower().endswith(('.wav', '.wave')):
        return read_wav(path)
    ext = os.path.splitext(path)[1].lower() or '(no extension)'
    raise Abort(
        'Detecting BPM from "%s" (%s) needs ffmpeg.\n'
        'Install ffmpeg and make sure it is on PATH, or set ffmpeg= in beat_mashup.cfg.\n'
        'WAV files work without ffmpeg.'
        % (os.path.basename(path), ext)
    )


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
            raise Abort('Audio is too short to detect tempo.')
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
        raise Abort('Audio is too short to detect tempo.')
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
        log('analysis: %.2f BPM, first beat %.3f s, in %.1f s' % (self.bpm, self.first_beat, time.time() - t0))

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


# --------------------------------------------------------------------------- cut plan
def _beat_weights(min_beats, max_beats):
    """Equal-weight dict for every allowed beat count in [min_beats, max_beats].
    Valid beat counts are 1, 2, 4 (the ones that divide a 4/4 bar evenly)."""
    allowed = [L for L in (1, 2, 4) if min_beats <= L <= max_beats]
    if not allowed:
        # Clamp to nearest valid value
        allowed = [min((1, 2, 4), key=lambda L: abs(L - min_beats))]
    return {L: 1 for L in allowed}


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


# --------------------------------------------------------------------------- transient snapping
def snap_bounds_to_hits(bounds, analysis, bpm, threshold):
    """Shift each cut boundary to the nearest loud transient within ±half a beat.

    Parameters
    ----------
    bounds    : list of seconds (from plan_bounds) — modified in place and returned
    analysis  : Analysis object (provides .nov, .efps, .latency)
    bpm       : float
    threshold : 0–1 fraction of the global peak; boundaries where no onset
                exceeds this level are left unchanged

    Returns
    -------
    (snapped_bounds, n_snapped) – list of floats and count of moved boundaries
    """
    nov = analysis.nov
    efps = analysis.efps
    half_beat_frames = (60.0 / bpm / 2.0) * efps  # half-beat window in envelope frames

    # Global peak for threshold normalisation (ignore first and last frame)
    peak = max(nov[1:-1]) if len(nov) > 2 else 1.0
    if peak <= 0:
        return bounds, 0

    abs_threshold = threshold * peak
    n_snapped = 0

    out = [bounds[0]]  # index 0 (t=0) is never moved
    for t in bounds[1:]:
        center = t * efps  # position in envelope frames
        lo = max(0, int(center - half_beat_frames))
        hi = min(len(nov) - 1, int(center + half_beat_frames) + 1)

        # Find the loudest onset in the window
        best_idx, best_val = lo, nov[lo]
        for idx in range(lo + 1, hi + 1):
            if nov[idx] > best_val:
                best_val, best_idx = nov[idx], idx

        if best_val >= abs_threshold:
            new_t = best_idx / efps
            if abs(new_t - t) > 1e-4:   # only count as snapped if it actually moved
                n_snapped += 1
            out.append(new_t)
        else:
            out.append(t)

    return out, n_snapped


# --------------------------------------------------------------------------- clip picking
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


# --------------------------------------------------------------------------- dialog (optional)
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

    def row(label, widget):
        return ui.HGroup({'Weight': 0}, [ui.Label({'Text': label, 'Weight': 0.55}), widget])

    win = disp.AddWindow({'ID': 'BeatMashup', 'WindowTitle': 'Beat mashup', 'Geometry': [300, 200, 430, 500]}, [
        ui.VGroup({'Spacing': 6}, [
            ui.Label({'Text': info, 'WordWrap': True, 'Weight': 0}),
            ui.VGap(4),
            row('BPM (0 = detect)', ui.DoubleSpinBox({'ID': 'bpm', 'Minimum': 0, 'Maximum': 400, 'Decimals': 2,
                                                      'Value': float(cfg['bpm'] or 0), 'Weight': 0.45})),
            row('First beat in s (-1 = detect)', ui.DoubleSpinBox({
                'ID': 'first', 'Minimum': -1, 'Maximum': 60, 'Decimals': 3, 'SingleStep': 0.01,
                'Value': -1.0 if cfg['first_beat'] is None else float(cfg['first_beat']), 'Weight': 0.45})),
            row('Bar shift (-1 = detect)', ui.SpinBox({
                'ID': 'shift', 'Minimum': -1, 'Maximum': 3,
                'Value': -1 if cfg['bar_shift'] is None else int(cfg['bar_shift']), 'Weight': 0.45})),
            row('Duration in s (0 = song)', ui.DoubleSpinBox({'ID': 'dur', 'Minimum': 0, 'Maximum': 36000,
                                                              'Decimals': 1, 'Value': float(cfg['duration'] or 0),
                                                              'Weight': 0.45})),
            row('Min beats per cut (1/2/4)', ui.SpinBox({'ID': 'minb', 'Minimum': 1, 'Maximum': 4,
                                                         'Value': int(cfg['min_beats']), 'Weight': 0.45})),
            row('Max beats per cut (1/2/4)', ui.SpinBox({'ID': 'maxb', 'Minimum': 1, 'Maximum': 4,
                                                         'Value': int(cfg['max_beats']), 'Weight': 0.45})),
            ui.CheckBox({'ID': 'snap', 'Text': 'Snap cuts to loudest hits (snares/claps)',
                         'Checked': bool(cfg['snap_to_hits']), 'Weight': 0}),
            row('Hit threshold (0–1)', ui.DoubleSpinBox({'ID': 'thresh', 'Minimum': 0.0, 'Maximum': 1.0,
                                                         'Decimals': 2, 'SingleStep': 0.05,
                                                         'Value': float(cfg['hit_threshold']), 'Weight': 0.45})),
            row('Seed (empty = random)', ui.LineEdit({'ID': 'seed',
                                                      'Text': '' if cfg['seed'] is None else str(cfg['seed']),
                                                      'Weight': 0.45})),
            row('Marker every N bars', ui.SpinBox({'ID': 'marks', 'Minimum': 0, 'Maximum': 64,
                                                   'Value': int(cfg['markers_every_bars']), 'Weight': 0.45})),
            row('Timeline', ui.LineEdit({'ID': 'name', 'Text': cfg['timeline_name'], 'Weight': 0.45})),
            ui.CheckBox({'ID': 'reuse', 'Text': 'Avoid repeating the same stretch of a video',
                         'Checked': bool(cfg['avoid_reuse']), 'Weight': 0}),
            ui.Label({'Text': 'Only V1 and A1 are rebuilt. Put your FX on V2 or above.',
                      'WordWrap': True, 'Weight': 0}),
            ui.HGroup({'Weight': 0}, [ui.Button({'ID': 'cancel', 'Text': 'Cancel'}),
                                      ui.Button({'ID': 'ok', 'Text': 'Generate', 'Default': True})]),
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
    out['min_beats'] = int(items['minb'].Value)
    out['max_beats'] = int(items['maxb'].Value)
    out['snap_to_hits'] = bool(items['snap'].Checked)
    out['hit_threshold'] = float(items['thresh'].Value)
    seed = str(items['seed'].Text).strip()
    out['seed'] = int(seed) if seed.lstrip('-').isdigit() else (seed or None)
    out['markers_every_bars'] = int(items['marks'].Value)
    out['timeline_name'] = str(items['name'].Text).strip() or cfg['timeline_name']
    out['avoid_reuse'] = bool(items['reuse'].Checked)
    return out


def show_message(ui, disp, title, text):
    if ui is not None and disp is not None:
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
            return
        except Exception:
            pass
    # Fallback when Resolve UIManager is not available (e.g. Free version)
    try:
        if sys.platform == 'darwin':
            safe_text = str(text).replace('\\', '\\\\').replace('"', '\\"')
            safe_title = str(title).replace('\\', '\\\\').replace('"', '\\"')
            subprocess.run(['osascript', '-e',
                            f'display dialog "{safe_text}" with title "{safe_title}" buttons {{"OK"}} default button "OK"'],
                           check=False)
        elif sys.platform.startswith('win'):
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, str(text), str(title), 0)
    except Exception:
        pass


# --------------------------------------------------------------------------- edit
def build(resolve, cfg, ui=None, disp=None):
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        raise Abort('No project is open.')
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

    info = 'Bin "%s": %d video(s). Song: %s' % (folder_name, len(videos), song.name if song else 'none')
    if ui is not None and cfg.get('show_dialog'):
        cfg = ask_options(ui, disp, cfg, info)
        if cfg is None:
            log('cancelled')
            return None
    log(info)
    if not videos:
        raise Abort('No videos in Media Pool bin "%s". Open the bin with your clips and run again.'
                    % folder_name)

    # Build beat_weights from min/max range
    weights = _beat_weights(cfg.get('min_beats', 1), cfg.get('max_beats', 4))
    if not any(w > 0 for w in weights.values()):
        raise Abort('All cut weights are 0.')

    # ---- tempo
    bpm = float(cfg['bpm'] or 0)
    analysis = None
    if song and (bpm <= 0 or cfg['first_beat'] is None or cfg['bar_shift'] is None):
        if not song.path or not os.path.exists(song.path):
            if bpm <= 0:
                raise Abort('Cannot find the file for "%s" on disk to detect BPM.' % song.name)
        else:
            log('analyzing', song.name, '...')
            analysis = Analysis(song.path, tuple(cfg['tempo_range']), cfg['ffmpeg'])
    if bpm <= 0:
        if not analysis:
            raise Abort('Type the BPM or add the song to the Media Pool so it can be detected.')
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
            raise Abort('A timeline named "%s" already exists and this script did not create it. Change the name '
                        'in the options so it is not overwritten.' % name)
        project.SetCurrentTimeline(tl)
        if v1 or a1:
            if not tl.DeleteClips(list(v1) + list(a1), False):
                raise Abort('Could not delete previous V1/A1 clips (locked track?).')
        for f in ours:
            tl.DeleteMarkerAtFrame(f)
        log('regenerating V1 and A1 of "%s"; other tracks are left alone' % name)
    else:
        tl = pool.CreateEmptyTimeline(name)
        if not tl:
            raise Abort('Could not create timeline "%s".' % name)
        project.SetCurrentTimeline(tl)
        log('new timeline "%s"' % name)

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
    bounds = plan_bounds(duration, bpm, first_beat, bar_shift, weights, rng, fps)

    # ---- optional transient snapping
    snap_count = 0
    if cfg.get('snap_to_hits') and analysis is not None:
        bounds, snap_count = snap_bounds_to_hits(bounds, analysis, bpm, cfg.get('hit_threshold', 0.35))
        log('snapped %d/%d boundaries to nearby hits' % (snap_count, max(0, len(bounds) - 1)))

    grid = [int(round(b * fps)) for b in bounds]
    log('%.2f BPM, first beat %.3f s, bar shift %d, %d cuts, %.1f s, seed %s'
        % (bpm, first_beat, bar_shift, len(bounds) - 1, duration, seed))

    # ---- song on A1
    song_items = []
    if song:
        song_fps = song.fps or fps
        n = max(1, min(song.frames, int(round(duration * song_fps))))
        got = pool.AppendToTimeline([{'mediaPoolItem': song.item, 'startFrame': 0, 'endFrame': n - 1,
                                      'mediaType': 2, 'trackIndex': 1, 'recordFrame': start}])
        if not got:
            log('warning: could not place the song on A1')
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
            raise Abort('Resolve rejected cut %d (%s, frames %d-%d).' % (i + 1, clip.name, s, e))
        item = got[0]
        at, dur = int(item.GetStart()), int(item.GetDuration())
        if placed == 0 and at != rec:
            tl.DeleteClips([item] + song_items, False)
            raise Abort('This Resolve build ignores "recordFrame" when adding clips; you need a newer '
                        'version for this script.')
        if not calibrated and abs((clip.fps or fps) - fps) < 1e-3:
            calibrated = True
            if dur == need - 1 + end_adjust:
                end_adjust = 1  # this Resolve treats endFrame as exclusive
        rec = at + dur
        prev = clip.uid
        placed += 1
        if placed % 50 == 0:
            log('%d cuts...' % placed)

    # ---- markers
    snap_note = (', %d hits snapped' % snap_count) if snap_count else ''
    info_note = '%.2f BPM · first beat %.3f s · bar +%d · seed %s · %d cuts%s' % (
        bpm, first_beat, bar_shift, seed, placed, snap_note)
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
                        tl.AddMarker(f, 'Sky', 'Bar %d' % (bar + 1), '', 1, TAG + ':bar')
                bar += 1
            k += 1

    min_b = cfg.get('min_beats', 1)
    max_b = cfg.get('max_beats', 4)
    beat_desc = ('%d-%d beats' % (min_b, max_b)) if min_b != max_b else ('%d beats' % min_b)
    msg = ('%d cuts at %.2f BPM (%s) on "%s" (seed %s, %.1f s).%s\nYour FX on V2+ were kept.'
           % (placed, bpm, beat_desc, name, seed, time.time() - t0,
              ('\n%d cuts snapped to hits.' % snap_count) if snap_count else ''))
    log(msg.replace('\n', ' '))
    return {'timeline': tl, 'bpm': bpm, 'first_beat': first_beat, 'bar_shift': bar_shift, 'seed': seed,
            'cuts': placed, 'grid': grid, 'start': start, 'fps': fps, 'message': msg}


def main():
    resolve = get_resolve()
    if resolve is None:
        log('Cannot find Resolve. Run this from Workspace > Scripts inside DaVinci Resolve.')
        show_message(None, None, 'Beat mashup',
                     'Cannot find Resolve. Run this from Workspace > Scripts inside DaVinci Resolve.')
        return
    cfg = load_config(dict(CONFIG))
    ui, disp = get_ui(resolve) if cfg.get('show_dialog') else (None, None)
    try:
        res = build(resolve, cfg, ui, disp)
        if res:
            show_message(ui, disp, 'Beat mashup', res['message'])
    except Abort as e:
        log('ERROR:', e)
        show_message(ui, disp, 'Beat mashup', str(e))
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        log('ERROR: unexpected exception:\n', err_msg)
        show_message(ui, disp, 'Beat mashup', f'Unexpected error:\n{e}')


if __name__ == '__main__' or 'resolve' in globals() or 'app' in globals():
    main()
