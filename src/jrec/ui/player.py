"""Playback through ffplay in a child process (the UI never decodes audio itself).

Sound modes are for listening only; files are never changed:
  original  the raw clip, exactly as recorded
  clearer   a live ffmpeg filter (rumble cut, FFT denoise, gentle level evening)
  cleaned   the DeepFilterNet listening copy listen.opus (made by `jrec enhance`)
"""
import subprocess
import time

CLEARER = "highpass=f=90,lowpass=f=7800,afftdn=nr=14:nf=-32:tn=1,dynaudnorm=f=200:g=11"
CHANNEL = {"both": None, "left": "pan=mono|c0=FL", "right": "pan=mono|c0=FR"}


class Player:
    def __init__(self):
        self.proc, self.t0, self.wall0, self.conv = None, 0.0, 0.0, None
        self.speed, self.sound, self.channel = 1.0, "original", "both"

    def source(self, conv, t):
        listen = conv.folder / "listen.opus"
        if self.sound == "cleaned" and listen.exists():
            return listen, t
        acc = 0.0
        for p in conv.manifest["parts"]:
            d = p["t_end"] - p["t_start"]
            if t < acc + d:
                return conv.folder / p["file"], t - acc
            acc += d
        p = conv.manifest["parts"][-1]
        return conv.folder / p["file"], 0.0

    def filters(self):
        chain = [CHANNEL[self.channel]] if CHANNEL.get(self.channel) else []
        if self.sound == "clearer":
            chain.append(CLEARER)
        if self.speed != 1.0:
            chain.append(f"atempo={self.speed}")   # pitch-preserving
        return ",".join(chain)

    def play(self, conv, t, speed=None):
        self.stop()
        if speed:
            self.speed = speed
        src, off = self.source(conv, max(0.0, t))
        af = self.filters()
        self.proc = subprocess.Popen(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-ss", f"{off:.3f}",
                                      *(["-af", af] if af else []), str(src)],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     close_fds=True)
        self.t0, self.wall0, self.conv = max(0.0, t), time.monotonic(), conv

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self.proc = None

    @property
    def playing(self):
        return self.proc is not None and self.proc.poll() is None

    def position(self):
        return self.t0 + (time.monotonic() - self.wall0) * self.speed if self.playing else None

    def restart(self):
        """Apply changed speed/sound/channel without losing the place."""
        if self.playing:
            self.play(self.conv, self.position())
