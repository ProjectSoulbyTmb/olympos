"""Procedural sound effects for the Bifrost client.

Every sound is synthesised at startup with numpy - no audio files,
nothing copyrighted. If the mixer cannot start (headless, missing
device) the Audio object degrades to silent no-ops.
"""
import numpy


class Audio:
    def __init__(self, pygame):
        self.enabled = False
        self.snd = {}
        try:
            pygame.mixer.pre_init(22050, -16, 1, 256)
            pygame.mixer.init()
            self.snd = self._build(pygame)
            self.enabled = bool(self.snd)
        except Exception:
            self.enabled = False

    def _tone(self, freq, ms, vol=0.4, shape="sine", decay=6.0):
        sr = 22050
        n = int(sr * ms / 1000)
        t = numpy.linspace(0, ms / 1000, n, endpoint=False)
        if shape == "square":
            wave = numpy.sign(numpy.sin(2 * numpy.pi * freq * t))
        elif shape == "noise":
            rng = numpy.random.default_rng(freq)
            wave = rng.uniform(-1, 1, n)
        else:
            wave = numpy.sin(2 * numpy.pi * freq * t)
        env = numpy.exp(-decay * t)
        data = (wave * env * vol * 32767).astype(numpy.int16)
        return data.tobytes()

    def _seq(self, chunks):
        out = []
        for c in chunks:
            out.append(c)
            out.append(self._tone(1, 30, 0.0))
        return b"".join(out)

    def _build(self, pygame):
        s = {
            "chop": pygame.mixer.Sound(
                buffer=self._tone(140, 90, 0.5, "noise", 22)),
            "mine": pygame.mixer.Sound(
                buffer=self._tone(320, 80, 0.45, "square", 20)),
            "splash": pygame.mixer.Sound(
                buffer=self._tone(700, 120, 0.3, "noise", 14)),
            "hit": pygame.mixer.Sound(
                buffer=self._tone(180, 110, 0.5, "square", 16)),
            "kill": pygame.mixer.Sound(buffer=self._seq([
                self._tone(392, 90, 0.35),
                self._tone(523, 130, 0.4)])),
            "coin": pygame.mixer.Sound(buffer=self._seq([
                self._tone(1180, 60, 0.3),
                self._tone(1560, 100, 0.3)])),
            "eat": pygame.mixer.Sound(
                buffer=self._tone(220, 140, 0.35, "sine", 9)),
            "cast": pygame.mixer.Sound(
                buffer=self._tone(880, 200, 0.3, "sine", 5)),
            "levelup": pygame.mixer.Sound(buffer=self._seq([
                self._tone(523, 90, 0.4),
                self._tone(659, 90, 0.4),
                self._tone(784, 160, 0.45)])),
            "step": pygame.mixer.Sound(
                buffer=self._tone(90, 40, 0.18, "noise", 26)),
            "steal": pygame.mixer.Sound(
                buffer=self._tone(500, 70, 0.25, "sine", 12)),
            "pray": pygame.mixer.Sound(
                buffer=self._tone(660, 260, 0.22, "sine", 3.5)),
            "teleport": pygame.mixer.Sound(buffer=self._seq([
                self._tone(300, 120, 0.3, "sine", 4),
                self._tone(900, 160, 0.28, "sine", 5)])),
        }
        for snd in s.values():
            snd.set_volume(0.55)
        return s

    # ---------- ambient loops (procedural WAV bytes) ----------

    def ambience(self, pygame, kind="surface"):
        """Return a looping Sound for an area, or None. Surface is a
        soft wind pad; catacombs a low ominous drone."""
        if not self.enabled:
            return None
        try:
            sr = 11025
            seconds = 4
            n = sr * seconds
            t = numpy.linspace(0, seconds, n, endpoint=False)
            rng = numpy.random.default_rng(7 if kind == "surface" else 13)
            noise = rng.uniform(-1, 1, n)
            kernel = numpy.ones(40) / 40.0
            smooth = numpy.convolve(noise, kernel, mode="same")
            if kind == "catacombs":
                drone = numpy.sin(2 * numpy.pi * 55 * t) * 0.5 \
                    + numpy.sin(2 * numpy.pi * 58 * t) * 0.5
                wave = smooth * 0.15 + drone * 0.25
            else:
                lfo = numpy.sin(2 * numpy.pi * 0.25 * t)
                wave = smooth * (0.12 + 0.08 * lfo)
            fade = numpy.minimum(1.0, numpy.minimum(t, seconds - t) * 4)
            wave *= fade
            data = (wave * 32767 * 0.35).astype(numpy.int16)
            snd = pygame.mixer.Sound(buffer=data.tobytes())
            return snd
        except Exception:
            return None

    def play(self, name):
        if not self.enabled:
            return
        snd = self.snd.get(name)
        if snd is not None:
            try:
                snd.play()
            except Exception:
                pass
