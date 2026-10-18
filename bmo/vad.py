"""Speech endpointing for the recorder: has the person started talking, and have they stopped?"""
import collections

import numpy as np

try:
    import webrtcvad
    from scipy.signal import butter, sosfilt
    HAS_VAD = True
except ImportError:
    HAS_VAD = False

VAD_RATES = (8000, 16000, 32000, 48000)
FRAME_S = 0.03


class Endpointer:
    # Loudness can't do this job on the USB mic: it runs hardware auto-gain and
    # ~99.9% of an idle room's energy is rumble below 300 Hz. So each frame is
    # high-passed at 200 Hz and classified by webrtcvad on spectral shape.

    def __init__(self, sr, silence_s=1.0, no_speech_s=3.5, aggressiveness=2):
        self.available = HAS_VAD and sr in VAD_RATES
        self.sr = sr
        self.frame_len = int(sr * FRAME_S)
        self.frames = 0
        self.voiced_frames = 0
        self.heard_speech = False

        self._skip = int(0.30 / FRAME_S)       # wake chime + filter warm-up
        self._grace = int(0.45 / FRAME_S)
        self._no_speech = int(no_speech_s / FRAME_S)
        # Measured: room noise peaks at 3/10 voiced frames, speech runs 7-10/10.
        self._onset = collections.deque(maxlen=10)
        n_tail = max(1, int(silence_s / FRAME_S))
        self._tail = collections.deque(maxlen=n_tail)
        self._tail_tolerance = max(2, n_tail // 8)
        self._mode = aggressiveness
        if self.available:
            self._sos = butter(4, 200, btype="highpass", fs=sr, output="sos")
            self._zi = np.zeros((self._sos.shape[0], 2))

    @property
    def voiced_seconds(self):
        return self.voiced_frames * FRAME_S

    @property
    def evidence(self):
        """'strong' = clearly speech; otherwise 'weak' / 'none'. Only 'strong' is
        trustworthy: on the USB mic a voice across the room can register zero
        voiced frames, so anything else still goes to Whisper for a second opinion."""
        if self.heard_speech:
            return "strong"
        return "weak" if self.voiced_frames >= 3 else "none"

    def push(self, frame):
        """Feed one mono float32 frame; returns True once the turn is over."""
        self.frames += 1
        voiced = self._is_speech(frame)
        if self.frames <= self._skip:
            return False

        if voiced:
            self.voiced_frames += 1
        self._onset.append(voiced)
        self._tail.append(voiced)

        if not self.heard_speech and sum(self._onset) >= 5:
            self.heard_speech = True
        if self.heard_speech:
            return self.frames >= self._grace and self._tail_quiet(self._tail_tolerance)
        # A quiet voice may never pass the onset test; keep listening while it
        # talks. Measured: a faint voice still flags ~15% of frames, room noise less.
        return self.frames >= self._no_speech and self._tail_quiet(2)

    def _tail_quiet(self, tolerance):
        return len(self._tail) == self._tail.maxlen and sum(self._tail) <= tolerance

    def _is_speech(self, frame):
        try:
            y, self._zi = sosfilt(self._sos, frame, zi=self._zi)
            pcm = (np.clip(y, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
            # Fresh Vad per frame: a long-lived one's hangover kept saying
            # "speech" ~1.8 s after talking stopped on this mic.
            return webrtcvad.Vad(self._mode).is_speech(pcm, self.sr)
        except Exception:
            return False
