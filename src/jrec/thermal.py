"""Wait while the machine is hot. The GB10 hard-reset under combined CPU+GPU load
(CPU zones reached 95 C; critical trip 104 C), so heavy steps start only when cool."""
import glob
import time

PAUSE_C = 90
RESUME_C = 82


def max_temp_c(pattern="/sys/class/thermal/thermal_zone*/temp"):
    vals = []
    for p in glob.glob(pattern):
        try:
            vals.append(int(open(p).read().strip()) / 1000)
        except (OSError, ValueError):
            pass
    return max(vals) if vals else None


def wait_cool(pause_c=PAUSE_C, resume_c=RESUME_C, log=print, sleep=time.sleep, read=max_temp_c):
    t = read()
    if t is None or t < pause_c:
        return 0.0
    log(f"  hot ({t:.0f} C): pausing until {resume_c} C")
    waited = 0.0
    while t is not None and t > resume_c:
        sleep(5)
        waited += 5
        t = read()
    log(f"  cooled to {t:.0f} C after {waited:.0f}s, continuing")
    return waited
