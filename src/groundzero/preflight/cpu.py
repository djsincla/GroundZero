"""CPU generation → ESXi 9 support classification.

Ported from the legacy ``compat/cpu.py`` rules (VCF 9.x support tiers). Ordered: first match wins,
so embedded/microserver parts are matched before the generic Xeon Scalable number patterns.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel


class CpuSupport(StrEnum):
    SUPPORTED = "supported"
    OVERRIDE_REQUIRED = "override_required"  # installs with the ESXi allowLegacyCPU / CPU override
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class CpuClass(BaseModel):
    family: str
    support: CpuSupport


_S, _O, _U = CpuSupport.SUPPORTED, CpuSupport.OVERRIDE_REQUIRED, CpuSupport.UNSUPPORTED

_RULES: tuple[tuple[str, str, CpuSupport], ...] = (
    # Embedded / microserver / entry parts
    (r"RYZEN EMBEDDED|\b(V1\d{3}|V2\d{3}|V3\d{3}|R1\d{3})\b", "AMD Ryzen Embedded", _U),
    (r"\bEPYC\s*3\d{3}\b", "AMD EPYC Embedded 3000", _U),
    (r"\bXEON\s+D[-\s]?(17|18|27|28)\d\d|\bD-(17|18|27|28)\d\d", "Intel Xeon D (Ice Lake-D)", _O),
    (r"\bXEON\s+D[-\s]?(15|16|21)\d\d|\bD-(15|16|21)\d\d", "Intel Xeon D-1500/1600/2100", _U),
    (r"\bE3-1\d{3}|\bXEON\s+E[-\s]?2[123]\d\d", "Intel Xeon E/E3 entry", _U),
    (r"\bATOM\b|DENVERTON|SNOW RIDGE", "Intel Atom", _U),
    # AMD EPYC
    (r"EPYC\s*9\d\d5|TURIN", "AMD EPYC 9005 (Turin)", _S),
    (r"EPYC\s*9\d\d4|GENOA|BERGAMO", "AMD EPYC 9004 (Genoa/Bergamo)", _S),
    (r"EPYC\s*8\d\d4|SIENA", "AMD EPYC 8004 (Siena)", _S),
    (r"EPYC\s*7\d\d[23]|ROME|MILAN", "AMD EPYC 7002/7003 (Rome/Milan)", _S),
    (r"EPYC\s*7\d\d1|NAPLES", "AMD EPYC 7001 (Naples)", _S),
    # Intel Xeon 6
    (r"\b69\d\d[PE]\b|GRANITE RAPIDS-AP", "Intel Xeon 6 6900", _S),
    (r"\b6[57]\d\d[PE]\b|GRANITE RAPIDS|SIERRA FOREST", "Intel Xeon 6 6700/6500", _S),
    # Intel Xeon Scalable (Gold 6230 → gen digit is the 2nd digit)
    (r"EMERALD RAPIDS|\b[34568]5\d\d[A-Z+]*\b", "Intel Xeon Scalable 5th Gen (Emerald Rapids)", _S),
    (r"SAPPHIRE RAPIDS|\b[34568]4\d\d[A-Z+]*\b", "Intel Xeon Scalable 4th Gen (Sapphire Rapids)", _S),
    (r"ICE LAKE|\b[34568]3\d\d[A-Z+]*\b", "Intel Xeon Scalable 3rd Gen (Ice Lake-SP)", _S),
    (r"CASCADE LAKE|\b[345689]2\d\d[A-Z+]*\b", "Intel Xeon Scalable 2nd Gen (Cascade Lake-SP)", _S),
    (r"SKYLAKE|\b[34568]1\d\d[A-Z+]*\b", "Intel Xeon Scalable 1st Gen (Skylake-SP)", _O),
    # Legacy / consumer
    (r"HASWELL|BROADWELL|\bE[57]-\d{4}", "Intel Xeon E5/E7 (pre-Skylake)", _U),
    (r"\bCORE\b|CELERON|PENTIUM", "Intel consumer CPU", _U),
    (r"RYZEN|ATHLON", "AMD consumer CPU", _U),
)
_COMPILED = tuple((re.compile(p), family, support) for p, family, support in _RULES)


def classify_cpu(model: str) -> CpuClass:
    text = model.upper()
    for pattern, family, support in _COMPILED:
        if pattern.search(text):
            return CpuClass(family=family, support=support)
    return CpuClass(family="Unrecognised CPU", support=CpuSupport.UNKNOWN)
