import subprocess
import csv
import re
import time
from datetime import datetime


# CONSTANTS

OUTPUT_FILE  : str = "lte_data.csv"
INTERVAL_SEC : float = 0.5
RUNS         : int = 10

HEADERS : list = [
    "deviceTime",
    "mcc", "mnc", "tac", "eci", "earfcn", "pci",
    "rsrp", "rsrq", "rssi", "snr", "ta",
    "provider", "servingCell", "lteBandwidth",
    "caEnabled", "caComponents", "caBandwidthsKhz",
    "cellChangeDetected", "signalDeltaRsrp",
    "latitude", "longitude", "altitude", "speed", "accuracy",
    "deviceSerialNumber",
]

SENTINEL : int = 2147483647

BW_MAP : dict = {
    "1400" : "1.4 MHz",
    "3000" : "3 MHz",
    "5000" : "5 MHz",
    "10000": "10 MHz",
    "15000": "15 MHz",
    "20000": "20 MHz",
}

BW_SCI_MAP : dict = {
    "1400" : "1.4e3",
    "3000" : "3e3",
    "5000" : "5e3",
    "10000": "1e4",
    "15000": "1.5e4",
    "20000": "2e4",
}


# FUNCTIONS

def run_adb(command: str, timeout: int = 12) -> str:
    """
    Runs an adb shell command and returns stdout.

    @ command : str = shell command to run
    @ timeout : int = max seconds to wait
    -> str    : raw stdout output, or empty string on failure
    """
    try:
        result : subprocess.CompletedProcess = subprocess.run(
            ["adb", "shell", command],
            capture_output=True, text=True, timeout=timeout
        )
        return result.stdout
    except Exception:
        return ""


def get_serial() -> str:
    """
    Retrieves the ADB device serial number.
    
    @ None
    -> str : serial number, or empty string on failure
    """
    try:
        result : subprocess.CompletedProcess = subprocess.run(
            ["adb", "get-serialno"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip()
    except Exception:
        return ""


def get_manufacturer() -> str:
    """
    Reads the device manufacturer from system properties.

    -> str : lowercase manufacturer name (e.g. 'xiaomi', 'samsung')
    """
    raw : str = run_adb("getprop ro.product.manufacturer")
    return raw.strip().lower()


def extract(pattern: str, text: str, fallback: str = "") -> str:
    """
    Returns the first capture group of pattern in text, or fallback.

    @ pattern  : str = regex pattern with exactly one capture group
    @ text     : str = text to search
    @ fallback : str = value to return when there is no match
    -> str     : matched group (stripped), or fallback
    """
    m = re.search(pattern, text)
    return m.group(1).strip() if m else fallback


def clean(val: str) -> str:
    """
    Strips Android sentinel values and blanks.
    Returns empty string when val is Integer.MAX_VALUE, its negative,
    an empty string, or the literal 'null'.

    @ val  : str = raw extracted value to sanitise
    -> str : original val if valid, otherwise empty string
    """
    return "" if val in (str(SENTINEL), str(-SENTINEL), "", "null") else val


def map_bandwidth(raw_val: str) -> str:
    """
    Converts a raw kHz bandwidth integer string to a human-readable MHz label.

    @ raw_val : str = bandwidth in kHz (e.g. '10000')
    -> str    : mapped label (e.g. '10 MHz'), raw value with unit if unmapped,
                or empty string when raw_val is empty
    """
    return BW_MAP.get(raw_val, f"{raw_val} kHz" if raw_val else "")


def to_sci_khz(raw_val: str) -> str:
    """
    Converts a raw kHz bandwidth integer string to a scientific notation label.

    @ raw_val : str = bandwidth in kHz (e.g. '10000')
    -> str    : scientific notation label (e.g. '1e4'), raw value if unmapped,
                or empty string when raw_val is empty
    """
    return BW_SCI_MAP.get(raw_val, raw_val)


def get_phone0_block(raw: str) -> str:
    """
    Isolates the Phone Id=0 block from dumpsys telephony.registry output.
    Prevents picking up garbage values from empty secondary SIM slots.

    @ raw  : str = full dumpsys telephony.registry output
    -> str : text content belonging to Phone Id=0 only;
             falls back to the full raw string when no split point is found
    """
    parts = re.split(r"Phone Id=\d+", raw)
    return parts[1] if len(parts) > 1 else raw


def parse_lte_signal(raw: str) -> dict:
    """
    Extracts LTE signal metrics from the mLte=CellSignalStrengthLte block,
    scoped to Phone Id=0.

    @ raw   : str  = full dumpsys telephony.registry output
    -> dict : keys rsrp, rsrq, rssi, snr, ta — all str, empty when absent
    """
    phone0 : str = get_phone0_block(raw)

    lte_match = re.search(r"mLte=CellSignalStrengthLte:([^\n,}]+)", phone0)
    if not lte_match:
        return {"rsrp": "", "rsrq": "", "rssi": "", "snr": "", "ta": ""}

    lte_block : str = lte_match.group(1)

    return {
        "rsrp": clean(extract(r"rsrp=(-?\d+)",  lte_block)),
        "rsrq": clean(extract(r"rsrq=(-?\d+)",  lte_block)),
        "rssi": clean(extract(r"rssi=(-?\d+)",  lte_block)),
        "snr" : clean(extract(r"rssnr=(-?\d+)", lte_block)),
        "ta"  : clean(extract(r"\bta=(\d+)",    lte_block)),
    }


def parse_cell_identity_xiaomi(phone0: str) -> dict:
    """
    Extracts cell identity fields using MIUI / HyperOS-specific field names.
    TAC and ECI are unavailable on Xiaomi due to modem restrictions.

    @ phone0 : str  = Phone Id=0 block from dumpsys telephony.registry
    -> dict  : keys mcc, mnc, tac, eci, earfcn, pci, lteBandwidth, provider
               — all str, empty when absent
    """
    ci_match = re.search(r"mCellIdentity=CellIdentityLte:\{([^}]+)\}", phone0)
    ci_block : str = ci_match.group(1) if ci_match else ""

    mcc      : str = clean(extract(r"mMcc=(\d+)",       ci_block))
    mnc      : str = clean(extract(r"mMnc=(\d+)",       ci_block))
    bw       : str = clean(extract(r"mBandwidth=(\d+)", ci_block))
    provider : str = extract(r"mAlphaLong=([^,\s}]+)",  ci_block)
    earfcn   : str = clean(extract(r"mChannelNumber=(\d+)", phone0))

    pci_match = re.search(
        r"mConnectionStatus=PrimaryServing[^}]*?mPhysicalCellId=(\d+)", phone0
    )
    pci : str = clean(pci_match.group(1) if pci_match else "")

    return {
        "mcc"         : mcc,
        "mnc"         : mnc,
        "tac"         : "",
        "eci"         : "",
        "earfcn"      : earfcn,
        "pci"         : pci,
        "lteBandwidth": map_bandwidth(bw),
        "provider"    : provider,
    }


def parse_cell_identity_samsung(phone0: str) -> dict:
    """
    Extracts cell identity fields using Samsung One UI field names.
    Samsung may use alternate casing or additional proprietary extensions.

    @ phone0 : str  = Phone Id=0 block from dumpsys telephony.registry
    -> dict  : keys mcc, mnc, tac, eci, earfcn, pci, lteBandwidth, provider
               — all str, empty when absent
    """
    ci_match = re.search(
        r"mCellIdentity(?:LTE|Lte)?[=:\s{]+([^}]+)\}",
        phone0, re.IGNORECASE
    )
    ci_block : str = ci_match.group(1) if ci_match else phone0

    mcc : str = clean(
        extract(r"mMccStr[=:\s]+(\d+)", ci_block) or
        extract(r"mMcc[=:\s]+(\d+)", ci_block)
    )
    mnc : str = clean(
        extract(r"mMncStr[=:\s]+(\d+)", ci_block) or
        extract(r"mMnc[=:\s]+(\d+)", ci_block)
    )
    tac : str = clean(
        extract(r"mTac[=:\s]+(\d+)", ci_block) or
        extract(r"\btac[=:\s]+(\d+)", ci_block)
    )
    eci : str = clean(
        extract(r"mCi[=:\s]+(\d+)", ci_block) or
        extract(r"mEci[=:\s]+(\d+)", ci_block)
    )
    earfcn : str = clean(
        extract(r"mEarfcn[=:\s]+(\d+)", ci_block) or
        extract(r"mChannelNumber[=:\s]+(\d+)", phone0)
    )
    pci : str = clean(
        extract(r"mPci[=:\s]+(\d+)", ci_block) or
        extract(r"mPhysicalCellId[=:\s]+(\d+)", phone0)
    )
    bw : str = clean(extract(r"mBandwidth[=:\s]+(\d+)", ci_block))
    provider : str = (
        extract(r"mAlphaLong=([^,\s}]+)", ci_block) or
        extract(r"mOperatorAlphaLong=([^,\s}]+)", ci_block)
    )

    if not pci:
        pci_match = re.search(
            r"mConnectionStatus=PrimaryServing[^}]*?mPhysicalCellId=(\d+)", phone0
        )
        pci = clean(pci_match.group(1) if pci_match else "")

    return {
        "mcc"         : mcc,
        "mnc"         : mnc,
        "tac"         : tac,
        "eci"         : eci,
        "earfcn"      : earfcn,
        "pci"         : pci,
        "lteBandwidth": map_bandwidth(bw),
        "provider"    : provider,
    }


def parse_cell_identity_pixel(phone0: str) -> dict:
    """
    Extracts cell identity fields for Google Pixel / stock AOSP devices.
    AOSP uses clean, well-documented field names that rarely deviate.

    @ phone0 : str  = Phone Id=0 block from dumpsys telephony.registry
    -> dict  : keys mcc, mnc, tac, eci, earfcn, pci, lteBandwidth, provider
               — all str, empty when absent
    """
    ci_match = re.search(
        r"CellIdentityLte\s*\{([^}]+)\}",
        phone0, re.IGNORECASE
    )
    ci_block : str = ci_match.group(1) if ci_match else phone0

    mcc    : str = clean(extract(r"mMcc=(\d+)",       ci_block))
    mnc    : str = clean(extract(r"mMnc=(\d+)",       ci_block))
    tac    : str = clean(extract(r"mTac=(\d+)",       ci_block))
    eci    : str = clean(extract(r"mCi=(\d+)",        ci_block))
    earfcn : str = clean(extract(r"mEarfcn=(\d+)",    ci_block))
    pci    : str = clean(extract(r"mPci=(\d+)",       ci_block))
    bw     : str = clean(extract(r"mBandwidth=(\d+)", ci_block))
    provider : str = extract(r"mAlphaLong=([^,\s}]+)", ci_block)

    if not pci:
        pci_match = re.search(
            r"mConnectionStatus=PrimaryServing[^}]*?mPhysicalCellId=(\d+)", phone0
        )
        pci = clean(pci_match.group(1) if pci_match else "")

    return {
        "mcc"         : mcc,
        "mnc"         : mnc,
        "tac"         : tac,
        "eci"         : eci,
        "earfcn"      : earfcn,
        "pci"         : pci,
        "lteBandwidth": map_bandwidth(bw),
        "provider"    : provider,
    }


def parse_cell_identity_motorola(phone0: str) -> dict:
    """
    Extracts cell identity fields for Motorola devices.
    Motorola stock Android is close to AOSP but occasionally uses
    alternate field casing or extra prefixes.

    @ phone0 : str  = Phone Id=0 block from dumpsys telephony.registry
    -> dict  : keys mcc, mnc, tac, eci, earfcn, pci, lteBandwidth, provider
               — all str, empty when absent
    """
    ci_match = re.search(
        r"mCellIdentity(?:LTE|Lte)?[=:\s{]+([^}]+)\}",
        phone0, re.IGNORECASE
    )
    ci_block : str = ci_match.group(1) if ci_match else phone0

    mcc    : str = clean(extract(r"mMcc(?:Str)?=(\d+)", ci_block))
    mnc    : str = clean(extract(r"mMnc(?:Str)?=(\d+)", ci_block))
    tac    : str = clean(extract(r"mTac=(\d+)",         ci_block))
    eci    : str = clean(
        extract(r"mCi=(\d+)", ci_block) or
        extract(r"mEci=(\d+)", ci_block)
    )
    earfcn : str = clean(
        extract(r"mEarfcn=(\d+)", ci_block) or
        extract(r"mChannelNumber=(\d+)", phone0)
    )
    pci    : str = clean(
        extract(r"mPci=(\d+)", ci_block) or
        extract(r"mPhysicalCellId=(\d+)", phone0)
    )
    bw     : str = clean(extract(r"mBandwidth=(\d+)", ci_block))
    provider : str = (
        extract(r"mAlphaLong=([^,\s}]+)", ci_block) or
        extract(r"mOperatorAlphaLong=([^,\s}]+)", ci_block)
    )

    if not pci:
        pci_match = re.search(
            r"mConnectionStatus=PrimaryServing[^}]*?mPhysicalCellId=(\d+)", phone0
        )
        pci = clean(pci_match.group(1) if pci_match else "")

    return {
        "mcc"         : mcc,
        "mnc"         : mnc,
        "tac"         : tac,
        "eci"         : eci,
        "earfcn"      : earfcn,
        "pci"         : pci,
        "lteBandwidth": map_bandwidth(bw),
        "provider"    : provider,
    }


def parse_cell_identity_oneplus(phone0: str) -> dict:
    """
    Extracts cell identity fields for OnePlus / Oppo / Realme devices.
    These brands share an OxygenOS / ColorOS base which closely follows
    AOSP field names but may embed extra vendor fields.

    @ phone0 : str  = Phone Id=0 block from dumpsys telephony.registry
    -> dict  : keys mcc, mnc, tac, eci, earfcn, pci, lteBandwidth, provider
               — all str, empty when absent
    """
    ci_match = re.search(
        r"mCellIdentity(?:LTE|Lte)?[=:\s{]+([^}]+)\}",
        phone0, re.IGNORECASE
    )
    ci_block : str = ci_match.group(1) if ci_match else phone0

    mcc    : str = clean(extract(r"mMcc(?:Str)?=(\d+)", ci_block))
    mnc    : str = clean(extract(r"mMnc(?:Str)?=(\d+)", ci_block))
    tac    : str = clean(extract(r"mTac=(\d+)",         ci_block))
    eci    : str = clean(extract(r"mCi=(\d+)",          ci_block))
    earfcn : str = clean(
        extract(r"mEarfcn=(\d+)",        ci_block) or
        extract(r"mChannelNumber=(\d+)", phone0)
    )
    pci    : str = clean(extract(r"mPci=(\d+)", ci_block))
    bw     : str = clean(extract(r"mBandwidth=(\d+)", ci_block))
    provider : str = extract(r"mAlphaLong=([^,\s}]+)", ci_block)

    if not pci:
        pci_match = re.search(
            r"mConnectionStatus=PrimaryServing[^}]*?mPhysicalCellId=(\d+)", phone0
        )
        pci = clean(pci_match.group(1) if pci_match else "")

    return {
        "mcc"         : mcc,
        "mnc"         : mnc,
        "tac"         : tac,
        "eci"         : eci,
        "earfcn"      : earfcn,
        "pci"         : pci,
        "lteBandwidth": map_bandwidth(bw),
        "provider"    : provider,
    }


def parse_cell_identity_generic(phone0: str) -> dict:
    """
    Extracts cell identity fields using multi-pattern matching to cover
    varying field names across Android OEMs not specifically handled above
    (Huawei, Nokia, Sony, HTC, etc.).

    @ phone0 : str  = Phone Id=0 block from dumpsys telephony.registry
    -> dict  : keys mcc, mnc, tac, eci, earfcn, pci, lteBandwidth, provider
               — all str, empty when absent
    """
    ci_match = re.search(
        r"mCellIdentity(?:LTE|Lte|LTE4G)?[=:\s{]+([^}]+)\}",
        phone0, re.IGNORECASE
    )
    ci_block : str = ci_match.group(1) if ci_match else phone0

    mcc : str = clean(
        extract(r"mMcc(?:Str)?[=:\s]+(\d+)", ci_block) or
        extract(r"\bmcc[=:\s]+(\d+)", ci_block)
    )
    mnc : str = clean(
        extract(r"mMnc(?:Str)?[=:\s]+(\d+)", ci_block) or
        extract(r"\bmnc[=:\s]+(\d+)", ci_block)
    )
    tac : str = clean(
        extract(r"mTac[=:\s]+(\d+)", ci_block) or
        extract(r"\btac[=:\s]+(\d+)", ci_block)
    )
    eci : str = clean(
        extract(r"mCi[=:\s]+(\d+)", ci_block) or
        extract(r"\bci[=:\s]+(\d+)", ci_block) or
        extract(r"mEci[=:\s]+(\d+)", ci_block)
    )
    earfcn : str = clean(
        extract(r"mEarfcn[=:\s]+(\d+)", ci_block) or
        extract(r"mChannelNumber[=:\s]+(\d+)", phone0) or
        extract(r"\bearfcn[=:\s]+(\d+)", ci_block)
    )
    pci : str = clean(
        extract(r"mPci[=:\s]+(\d+)", ci_block) or
        extract(r"mPhysicalCellId[=:\s]+(\d+)", phone0) or
        extract(r"\bpci[=:\s]+(\d+)", ci_block)
    )
    bw : str = clean(
        extract(r"mBandwidth[=:\s]+(\d+)", ci_block)
    )
    provider : str = (
        extract(r"mAlphaLong=([^,\s}]+)", ci_block) or
        extract(r"mOperatorAlphaLong=([^,\s}]+)", ci_block) or
        extract(r"operatorName=([^,\s}]+)", ci_block)
    )

    if not pci:
        pci_match = re.search(
            r"mConnectionStatus=PrimaryServing[^}]*?mPhysicalCellId=(\d+)", phone0
        )
        pci = clean(pci_match.group(1) if pci_match else "")

    return {
        "mcc"         : mcc,
        "mnc"         : mnc,
        "tac"         : tac,
        "eci"         : eci,
        "earfcn"      : earfcn,
        "pci"         : pci,
        "lteBandwidth": map_bandwidth(bw),
        "provider"    : provider,
    }


def parse_cell_identity(raw: str, manufacturer: str) -> dict:
    """
    Dispatches cell identity parsing to the appropriate OEM-specific
    or generic parser based on the detected device manufacturer.

    @ raw          : str  = full dumpsys telephony.registry output
    @ manufacturer : str  = lowercase manufacturer name from getprop
    -> dict        : keys mcc, mnc, tac, eci, earfcn, pci, lteBandwidth, provider
                     — all str, empty when absent
    """
    phone0 : str = get_phone0_block(raw)

    if any(b in manufacturer for b in ("xiaomi", "redmi", "poco")):
        return parse_cell_identity_xiaomi(phone0)

    if "samsung" in manufacturer:
        return parse_cell_identity_samsung(phone0)

    if "google" in manufacturer:
        return parse_cell_identity_pixel(phone0)

    if "motorola" in manufacturer or "moto" in manufacturer:
        return parse_cell_identity_motorola(phone0)

    if any(b in manufacturer for b in ("oneplus", "oppo", "realme")):
        return parse_cell_identity_oneplus(phone0)

    return parse_cell_identity_generic(phone0)


def parse_carrier_aggregation(raw: str) -> dict:
    """
    Extracts Carrier Aggregation state from mPhysicalChannelConfigs,
    scoped to Phone Id=0.

    @ raw   : str  = full dumpsys telephony.registry output
    -> dict : keys caEnabled (str 'true'/'false'), caComponents (str count),
              caBandwidthsKhz (str '+'-joined scientific notation) — empty when absent
    """
    phone0 : str = get_phone0_block(raw)

    configs_match = re.search(r"mPhysicalChannelConfigs=\[(.+?)\]", phone0, re.DOTALL)
    if not configs_match:
        return {"caEnabled": "", "caComponents": "", "caBandwidthsKhz": ""}

    configs_text : str = configs_match.group(1)

    bandwidths : list[str] = [
        b for b in re.findall(r"mCellBandwidthDownlinkKhz=(\d+)", configs_text)
        if b != str(SENTINEL)
    ]

    serving_count : int = len(
        re.findall(r"mConnectionStatus=(?:Primary|Secondary)Serving", configs_text)
    )

    return {
        "caEnabled"       : "true" if serving_count > 1 else "false",
        "caComponents"    : str(serving_count) if serving_count > 0 else "",
        "caBandwidthsKhz" : "+".join(to_sci_khz(b) for b in bandwidths) if bandwidths else "",
    }


def _parse_location_block(block: str) -> dict:
    """
    Parses a single location line in Android's compact bracket format:
      Location[fused 46.327177,21.694645 hAcc=100.0 et=... alt=164.5 vAcc=... vel=0.0]
    Also handles AOSP key=value variants (lat=, lon=, alt=, vel=, acc=).

    @ block : str  = one or more lines containing a location report
    -> dict : keys latitude, longitude, altitude, speed, accuracy
              — all str, empty when absent or zero
    """
    ZERO_VALS : set[str] = {"0.0", "0.000000", "0", ""}

    bracket = re.search(
        r"Location\[\w+\s+(-?\d+\.\d+),(-?\d+\.\d+)\s+hAcc=(-?\d+\.\d+)"
        r"(?:[^\]]*?alt=(-?\d+\.\d+))?(?:[^\]]*?vel=(-?\d+\.\d+))?",
        block
    )
    if bracket:
        lat  : str = bracket.group(1) or ""
        lon  : str = bracket.group(2) or ""
        acc  : str = bracket.group(3) or ""
        alt  : str = bracket.group(4) or ""
        spd  : str = bracket.group(5) or ""
    else:
        lat = (
            extract(r"\blat=(-?\d+\.\d+)",      block) or
            extract(r"latitude=(-?\d+\.\d+)",   block) or
            extract(r"mLatitude=(-?\d+\.\d+)",  block)
        )
        lon = (
            extract(r"\blon=(-?\d+\.\d+)",      block) or
            extract(r"longitude=(-?\d+\.\d+)",  block) or
            extract(r"mLongitude=(-?\d+\.\d+)", block)
        )
        alt = (
            extract(r"\balt=(-?\d+\.\d+)",      block) or
            extract(r"altitude=(-?\d+\.\d+)",   block) or
            extract(r"mAltitude=(-?\d+\.\d+)",  block)
        )
        spd = (
            extract(r"\bvel=(-?\d+\.\d+)",      block) or
            extract(r"speed=(-?\d+\.\d+)",      block) or
            extract(r"mSpeed=(-?\d+\.\d+)",     block)
        )
        acc = (
            extract(r"\bacc=(-?\d+\.\d+)",      block) or
            extract(r"hAcc=(-?\d+\.\d+)",       block) or
            extract(r"accuracy=(-?\d+\.\d+)",   block) or
            extract(r"mAccuracy=(-?\d+\.\d+)",  block)
        )

    return {
        "latitude" : "" if lat in ZERO_VALS else lat,
        "longitude": "" if lon in ZERO_VALS else lon,
        "altitude" : "" if alt in ZERO_VALS else alt,
        "speed"    : "" if spd in ZERO_VALS else spd,
        "accuracy" : "" if acc in ZERO_VALS else acc,
    }


def parse_location_xiaomi(raw: str) -> dict:
    """
    Parses GPS / fused location from Xiaomi / MIUI / HyperOS devices.
    MIUI can report location under the 'fused' or 'gps' provider using
    either the compact bracket format or long-form key=value fields.
    Delegates field extraction to _parse_location_block.

    @ raw   : str  = output from dumpsys location (grepped block)
    -> dict : keys latitude, longitude, altitude, speed, accuracy
              — all str, empty when absent or GPS not yet locked
    """
    return _parse_location_block(raw)


def parse_location_generic(raw: str) -> dict:
    """
    Parses dumpsys location output for non-Xiaomi devices.
    Handles both the compact bracket format used by the fused provider
    and the AOSP short key=value format.
    Delegates field extraction to _parse_location_block.

    @ raw   : str  = output from dumpsys location (grepped block)
    -> dict : keys latitude, longitude, altitude, speed, accuracy
              — all str, empty when absent or GPS not yet locked
    """
    return _parse_location_block(raw)


def parse_location(raw: str, manufacturer: str) -> dict:
    """
    Dispatches location parsing to the appropriate OEM-specific parser.

    @ raw          : str  = output from dumpsys location
    @ manufacturer : str  = lowercase manufacturer name
    -> dict        : keys latitude, longitude, altitude, speed, accuracy
                     — all str, empty when absent
    """
    if any(b in manufacturer for b in ("xiaomi", "redmi", "poco")):
        return parse_location_xiaomi(raw)

    return parse_location_generic(raw)


def get_location_dump(manufacturer: str) -> str:
    """
    Fetches the relevant location block from dumpsys location.
    Targets the 'last location' section which contains the most recent
    fused / GPS fix reported by LocationManagerService.

    @ manufacturer : str = lowercase manufacturer name
    -> str         : raw dumpsys output containing the location block
    """
    return run_adb("dumpsys location | grep -A 5 'last location'")


_prev_pci  : str = ""
_prev_rsrp : str = ""


def compute_l2_events(current_pci: str, current_rsrp: str) -> dict:
    """
    Derives L2 mobility events by comparing current values to the previous row.
    A PCI change signals a cell handover.
    signalDeltaRsrp is the dB change relative to the last sample.

    @ current_pci  : str  = Physical Cell ID of the current measurement
    @ current_rsrp : str  = RSRP value of the current measurement
    -> dict        : keys cellChangeDetected (str 'true'/'false'),
                     signalDeltaRsrp (str int) — empty on the very first sample
    """
    global _prev_pci, _prev_rsrp

    cell_change : str = ""
    delta_rsrp  : str = ""

    if _prev_pci and current_pci:
        cell_change = "true" if current_pci != _prev_pci else "false"

    if _prev_rsrp and current_rsrp:
        try:
            delta_rsrp = str(int(current_rsrp) - int(_prev_rsrp))
        except ValueError:
            delta_rsrp = ""

    _prev_pci  = current_pci
    _prev_rsrp = current_rsrp

    return {
        "cellChangeDetected": cell_change,
        "signalDeltaRsrp"   : delta_rsrp,
    }


def collect_row(serial: str, manufacturer: str) -> dict:
    """
    Collects one full measurement row using two ADB calls
    (telephony.registry and location).

    @ serial       : str  = device serial number
    @ manufacturer : str  = lowercase manufacturer name
    -> dict        : complete CSV row with all HEADERS keys populated,
                     empty string where data is unavailable
    """
    raw_registry : str = run_adb("dumpsys telephony.registry")
    raw_location : str = get_location_dump(manufacturer)
    timestamp    : str = datetime.now().astimezone().isoformat()

    signal   : dict = parse_lte_signal(raw_registry)
    identity : dict = parse_cell_identity(raw_registry, manufacturer)
    ca       : dict = parse_carrier_aggregation(raw_registry)
    location : dict = parse_location(raw_location, manufacturer)
    l2       : dict = compute_l2_events(identity.get("pci", ""), signal.get("rsrp", ""))

    return {
        "deviceTime"        : timestamp,
        "mcc"               : identity["mcc"],
        "mnc"               : identity["mnc"],
        "tac"               : identity["tac"],
        "eci"               : identity["eci"],
        "earfcn"            : identity["earfcn"],
        "pci"               : identity["pci"],
        "rsrp"              : signal["rsrp"],
        "rsrq"              : signal["rsrq"],
        "rssi"              : signal["rssi"],
        "snr"               : signal["snr"],
        "ta"                : signal["ta"],
        "provider"          : identity["provider"],
        "servingCell"       : "true",
        "lteBandwidth"      : identity["lteBandwidth"],
        "caEnabled"         : ca["caEnabled"],
        "caComponents"      : ca["caComponents"],
        "caBandwidthsKhz"   : ca["caBandwidthsKhz"],
        "cellChangeDetected": l2["cellChangeDetected"],
        "signalDeltaRsrp"   : l2["signalDeltaRsrp"],
        "latitude"          : location["latitude"],
        "longitude"         : location["longitude"],
        "altitude"          : location["altitude"],
        "speed"             : location["speed"],
        "accuracy"          : location["accuracy"],
        "deviceSerialNumber": serial,
    }


def write_header(writer: csv.DictWriter) -> None:
    """
    Writes the CSV header row.

    @ writer : csv.DictWriter = open writer instance
    -> None
    """
    writer.writeheader()


def write_row(writer: csv.DictWriter, row: dict) -> None:
    """
    Writes a single data row to the CSV.

    @ writer : csv.DictWriter = open writer instance
    @ row    : dict           = complete measurement row
    -> None
    """
    writer.writerow(row)


def run_loop(serial: str, manufacturer: str) -> None:
    """
    Main collection loop. Writes the CSV header once, then collects RUNS rows
    at INTERVAL_SEC cadence, flushing after each write.
    Progress is printed as [n/m] only — no field data is echoed to stdout.

    @ serial       : str = device serial number
    @ manufacturer : str = lowercase manufacturer name
    -> None
    """
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer : csv.DictWriter = csv.DictWriter(f, fieldnames=HEADERS)
        write_header(writer)

        count : int = 0
        while count < RUNS:
            row : dict = collect_row(serial, manufacturer)
            write_row(writer, row)
            f.flush()
            count += 1
            print(f"[{count:>{len(str(RUNS))}}/{RUNS}]")
            if count < RUNS:
                time.sleep(INTERVAL_SEC)

    print(f"\nDone — {RUNS} records saved to {OUTPUT_FILE}")


def main() -> None:
    """
    Entry point. Detects device serial and manufacturer, runs a preflight
    diagnostic row to surface missing fields early, then starts the
    collection loop.
    
    @ None
    -> None
    """
    print("Connecting to device...")
    serial : str = get_serial()
    if not serial or "error" in serial.lower():
        print("ERROR: No ADB device found. Check USB connection and USB Debugging.")
        return

    manufacturer : str = get_manufacturer()
    print(f"Device   : {serial}  ({manufacturer or 'unknown manufacturer'})")
    print(f"Output   : {OUTPUT_FILE}  |  interval {INTERVAL_SEC}s  |  {RUNS} runs\n")

    print("Preflight check...")
    diag : dict = collect_row(serial, manufacturer)

    expected_empty : set = {
        "cellChangeDetected", "signalDeltaRsrp",
        "latitude", "longitude", "altitude", "speed", "accuracy",
    }

    if any(b in manufacturer for b in ("xiaomi", "redmi", "poco")):
        expected_empty.update({"tac", "eci"})

    missing : list[str] = [
        k for k, v in diag.items()
        if v in ("", None) and k not in expected_empty
    ]

    if missing:
        print(f"WARNING  : missing fields — {', '.join(missing)}\n")
    else:
        print("OK       : all expected fields populated\n")

    run_loop(serial, manufacturer)


# ENTRY POINT

if __name__ == "__main__":
    main()