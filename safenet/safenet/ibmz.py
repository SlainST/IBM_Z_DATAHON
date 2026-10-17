"""What the hardware is, for /health: s390x, the IBM Z machine type and whether NNPA (the Telum AI unit) is there."""
import platform
import re
from functools import lru_cache

GENERATIONS = {"3931": "z16", "3932": "z16 / LinuxONE Rockhopper 4", "9175": "z17", "9176": "z17 / LinuxONE 5",
               "8561": "z15", "8562": "z15 / LinuxONE III"}


@lru_cache(maxsize=1)
def info() -> dict:
    arch = platform.machine()
    machine_type, nnpa = None, False
    try:
        cpuinfo = open("/proc/cpuinfo", encoding="utf-8").read()
        m = re.search(r"machine\s*=\s*([0-9A-Fa-f]+)", cpuinfo)
        machine_type = m.group(1) if m else None
        nnpa = bool(re.search(r"\bnnpa\b", cpuinfo))
    except OSError:
        pass
    return {"arch": arch, "machine_type": machine_type, "generation": GENERATIONS.get(machine_type or ""), "nnpa": nnpa}
