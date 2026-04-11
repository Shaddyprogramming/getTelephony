import re
from constants import SENTINEL, PROVIDER_ALIASES, XIAOMI_BRANDS


def extract(pattern: str, text: str, fallback: str = "") -> str:
    """
    Returns the first capture group of a pattern, or fallback.

    @ pattern  : str = regex with one capture group
    @ text     : str = text to search
    @ fallback : str = value returned on no match
    -> str     : matched group (stripped), or fallback
    """
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).strip() if m else fallback


def first_of(text: str, *patterns: str) -> str:
    """
    Returns the first capture group from the first matching pattern.

    @ text     : str   = text to search
    @ patterns : str   = regex patterns tried left-to-right, each with one capture group
    -> str     : first matched group (stripped), or empty string
    """
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def clean(val: str) -> str:
    """
    Strips sentinel values and nulls from a raw extracted value.

    @ val  : str = raw value to sanitise
    -> str : original val if valid, 'hidden' if sentinel, empty string otherwise
    """
    if val in (str(SENTINEL), str(-SENTINEL)):
        return "hidden"
    return "" if val in ("", "null") else val


def khz_to_mhz(khz: int) -> str:
    """
    Converts a kHz integer to a clean MHz string, dropping the decimal when whole.

    @ khz  : int = bandwidth value in kHz
    -> str : human-readable MHz label (e.g. '10 MHz', '1.4 MHz')
    """
    mhz = khz / 1000
    label = int(mhz) if mhz == int(mhz) else mhz
    return f"{label} MHz"


def format_bandwidth(raw_val: str) -> str:
    """
    Converts a raw kHz bandwidth string to a readable MHz or kHz label.

    @ raw_val : str = bandwidth in kHz as a string (e.g. '10000', '1400')
    -> str    : MHz label when >= 1000 kHz, kHz label otherwise, empty when absent
    """
    if not raw_val:
        return ""
    try:
        khz = int(raw_val)
        return khz_to_mhz(khz) if khz >= 1000 else f"{khz} kHz"
    except ValueError:
        return raw_val


def normalize_provider(raw: str) -> str:
    """
    Maps a raw operator name to a canonical display name.

    @ raw  : str = operator string from dumpsys (e.g. 'ORANGE RO')
    -> str : canonical name (e.g. 'Orange'), or original if unrecognised
    """
    lower = raw.lower().strip()
    for key, canonical in PROVIDER_ALIASES.items():
        if key in lower or lower == key:
            return canonical
    return raw


def get_phone0_block(raw: str) -> str:
    """
    Returns the Phone Id block containing active LTE data.

    @ raw  : str = full dumpsys telephony.registry output
    -> str : content of the active Phone Id block
    """
    parts = re.split(r"Phone Id=\d+", raw)
    if len(parts) <= 1:
        return raw
    blocks = parts[1:]
    for block in blocks:
        if re.search(r"CellIdentityLte[^n]", block):
            return block
    return blocks[0]


def parse_lte_signal(raw: str) -> dict:
    """
    Extracts LTE signal metrics from the mSignalStrength block.

    @ raw   : str  = full dumpsys telephony.registry output
    -> dict : keys rsrp, rsrq, rssi, snr, ta — all str, empty when absent
    """
    phone0    : str = get_phone0_block(raw)
    lte_block : str = ""

    m = re.search(r"mLte=CellSignalStrengthLte[:\s]*([^\n,}]+)", phone0)
    if m:
        lte_block = m.group(1)
    else:
        m = re.search(r"CellSignalStrengthLte[:\s]+([^\n}]+)", phone0)
        if m:
            lte_block = m.group(1)

    if not lte_block:
        return {"rsrp": "", "rsrq": "", "rssi": "", "snr": "", "ta": ""}

    return {
        "rsrp": clean(extract(r"rsrp=(-?\d+)",  lte_block)),
        "rsrq": clean(extract(r"rsrq=(-?\d+)",  lte_block)),
        "rssi": clean(extract(r"rssi=(-?\d+)",  lte_block)),
        "snr" : clean(first_of(lte_block, r"rssnr=(-?\d+)", r"\bsnr=(-?\d+)")),
        "ta"  : clean(extract(r"\bta=(\d+)",    lte_block)),
    }


def parse_cell_identity(raw: str, manufacturer: str) -> dict:
    """
    Extracts cell identity fields from dumpsys telephony.registry.

    @ raw          : str  = full dumpsys telephony.registry output
    @ manufacturer : str  = lowercase manufacturer name from getprop
    -> dict        : keys mcc, mnc, tac, eci, earfcn, pci, lteBandwidth, provider
                     — all str, empty when absent
    """
    phone0   : str = get_phone0_block(raw)
    ci_block : str = ""

    for pattern in (r"CellIdentityLte[:\s]*\{([^}]+)\}", r"mCellIdentity(?:LTE|Lte|LTE4G)?[=:\s{]+([^}]+)\}"):
        m = re.search(pattern, phone0, re.IGNORECASE)
        if m:
            ci_block = m.group(1)
            break
    if not ci_block:
        ci_block = phone0

    mcc = clean(first_of(ci_block, r"mMcc(?:Str)?[=:\s]+(\d+)", r"\bmcc[=:\s]+(\d+)"))
    mnc = clean(first_of(ci_block, r"mMnc(?:Str)?[=:\s]+(\d+)", r"\bmnc[=:\s]+(\d+)"))

    is_xiaomi : bool = any(b in manufacturer for b in XIAOMI_BRANDS)

    tac = "hidden" if is_xiaomi else clean(first_of(ci_block, r"mTac[=:\s]+(\d+)", r"\btac[=:\s]+(\d+)"))
    eci = "hidden" if is_xiaomi else clean(first_of(ci_block, r"mCi[=:\s]+(\d+)", r"mEci[=:\s]+(\d+)", r"\bci[=:\s]+(\d+)"))

    earfcn = clean(first_of(
        ci_block + "\n" + phone0,
        r"mEarfcn[=:\s]+(\d+)", r"mChannelNumber[=:\s]+(\d+)",
        r"mDownlinkChannelNumber[=:\s]+(\d+)", r"\bearfcn[=:\s]+(\d+)",
    ))

    pci = clean(first_of(ci_block, r"mPci[=:\s]+(\d+)", r"mPhysicalCellId[=:\s]+(\d+)", r"\bpci[=:\s]+(\d+)"))
    if not pci:
        m = re.search(r"mConnectionStatus=PrimaryServing[^}]*?mPhysicalCellId=(\d+)", phone0)
        pci = clean(m.group(1) if m else "")

    bw_raw = clean(first_of(ci_block, r"mBandwidth[=:\s]+(\d+)"))
    if not bw_raw:
        m = re.search(r"mConnectionStatus=PrimaryServing[^}]*?mCellBandwidthDownlinkKhz=(\d+)", phone0)
        if m and m.group(1) != str(SENTINEL):
            bw_raw = m.group(1)

    provider = normalize_provider(first_of(
        ci_block,
        r"mAlphaLong=([^,\s}]+)",
        r"mOperatorAlphaLong=([^,\s}]+)",
        r"operatorName=([^,\s}]+)",
    ))

    return {
        "mcc"         : mcc,
        "mnc"         : mnc,
        "tac"         : tac,
        "eci"         : eci,
        "earfcn"      : earfcn,
        "pci"         : pci,
        "lteBandwidth": format_bandwidth(bw_raw),
        "provider"    : provider,
    }


def parse_carrier_aggregation(raw: str) -> dict:
    """
    Extracts Carrier Aggregation state from mPhysicalChannelConfigs.

    @ raw   : str  = full dumpsys telephony.registry output
    -> dict : keys caEnabled (str 'true'/'false'), caComponents (str count),
              caBandwidthsKhz (str '+'-joined MHz labels) — empty when absent
    """
    phone0 : str = get_phone0_block(raw)

    m = re.search(r"(?:mPhysicalChannelConfigs|PhysicalChannelConfigs)=\[(.+?)\]", phone0, re.DOTALL | re.IGNORECASE)
    if not m:
        return {"caEnabled": "", "caComponents": "", "caBandwidthsKhz": ""}

    configs_text : str = m.group(1)

    bandwidths : list[str] = [
        b for b in re.findall(r"mCellBandwidthDownlinkKhz=(\d+)", configs_text)
        if b != str(SENTINEL)
    ]
    serving_count : int = len(re.findall(r"mConnectionStatus=(?:Primary|Secondary)Serving", configs_text))

    return {
        "caEnabled"      : "true" if serving_count > 1 else "false",
        "caComponents"   : str(serving_count) if serving_count > 0 else "",
        "caBandwidthsKhz": "+".join(format_bandwidth(b) for b in bandwidths) if bandwidths else "",
    }


def parse_location(raw: str) -> dict:
    """
    Parses a location block from dumpsys location output.

    @ raw   : str  = raw location block (bracket or key=value format)
    -> dict : keys latitude, longitude, altitude, speed, accuracy
              — all str, empty when absent or zero
    """
    ZERO_VALS : set = {"0.0", "0.000000", "0", ""}

    bracket = re.search(
        r"Location\[\w+\s+(-?\d+\.\d+),(-?\d+\.\d+)\s+hAcc=(-?\d+\.\d+)"
        r"(?:[^\]]*?alt=(-?\d+\.\d+))?(?:[^\]]*?vel=(-?\d+\.\d+))?",
        raw
    )
    if bracket:
        lat = bracket.group(1) or ""
        lon = bracket.group(2) or ""
        acc = bracket.group(3) or ""
        alt = bracket.group(4) or ""
        spd = bracket.group(5) or ""
    else:
        lat = first_of(raw, r"\blat=(-?\d+\.\d+)", r"latitude=(-?\d+\.\d+)", r"mLatitude=(-?\d+\.\d+)")
        lon = first_of(raw, r"\blon=(-?\d+\.\d+)", r"longitude=(-?\d+\.\d+)", r"mLongitude=(-?\d+\.\d+)")
        alt = first_of(raw, r"\balt=(-?\d+\.\d+)", r"altitude=(-?\d+\.\d+)", r"mAltitude=(-?\d+\.\d+)")
        spd = first_of(raw, r"\bvel=(-?\d+\.\d+)", r"speed=(-?\d+\.\d+)", r"mSpeed=(-?\d+\.\d+)")
        acc = first_of(raw, r"\bacc=(-?\d+\.\d+)", r"hAcc=(-?\d+\.\d+)", r"accuracy=(-?\d+\.\d+)", r"mAccuracy=(-?\d+\.\d+)")

    return {
        "latitude" : "" if lat in ZERO_VALS else lat,
        "longitude": "" if lon in ZERO_VALS else lon,
        "altitude" : "" if alt in ZERO_VALS else alt,
        "speed"    : "0" if spd in ZERO_VALS else spd,
        "accuracy" : "" if acc in ZERO_VALS else acc,
    }