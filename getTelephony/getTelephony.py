import subprocess
import csv
import re
import time
from datetime import datetime


# CONSTANTS

OUTPUT_FILE  : str   = "lte_data.csv"
INTERVAL_SEC : float = 0.5
RUNS         : int   = 10

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
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).strip() if m else fallback


def first_of(text: str, *patterns: str) -> str:
    """
    Tries each pattern in order and returns the first match found.
    All patterns must have exactly one capture group.

    @ text     : str   = text to search
    @ patterns : str   = one or more regex patterns, tried left-to-right
    -> str     : first matched group (stripped), or empty string
    """
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def clean(val: str) -> str:
    """
    Strips Android sentinel values and blanks.
    Returns "hidden" when val is Integer.MAX_VALUE or its negative
    (value exists but is restricted by the device), empty string when
    val is blank or null.

    @ val  : str = raw extracted value to sanitise
    -> str : original val if valid, "hidden" if sentinel, otherwise empty string
    """
    if val in (str(SENTINEL), str(-SENTINEL)):
        return "hidden"
    return "" if val in ("", "null") else val


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
    Returns the Phone Id block that contains active LTE data.
 
    Splits the dump on 'Phone Id=N' boundaries and picks the first block
    that contains a non-null CellIdentityLte entry. This handles dual-SIM
    devices where the active SIM is in slot 1 (or higher) rather than
    slot 0 — e.g. Samsung S24 with SIM in slot 1 reports everything under
    Phone Id=1 while Phone Id=0 is empty.
 
    Falls back to the first block if no block contains cell data, and to
    the full raw string if there are no split points at all.
 
    @ raw  : str = full dumpsys telephony.registry output
    -> str : text content of the active Phone Id block
    """
    parts = re.split(r"Phone Id=\d+", raw)
    if len(parts) <= 1:
        return raw
 
    # Skip parts[0] — it is the text before the first "Phone Id=" marker
    blocks = parts[1:]
 
    # Prefer the first block that has a real (non-null) CellIdentityLte
    for block in blocks:
        if re.search(r"CellIdentityLte[^n]", block):  # excludes "CellIdentityLte:null"
            return block
 
    # Nothing matched — return first block as original behaviour
    return blocks[0]


def parse_lte_signal(raw: str) -> dict:
    """
    Extracts LTE signal metrics from the mSignalStrength block,
    scoped to Phone Id=0.

    Handles two formats found across Android OEMs:
      - Wrapped:   mLte=CellSignalStrengthLte: rssi=... rsrp=...
      - Flat:      CellSignalStrengthLte: rssi=... rsrp=...   (S24 / One UI 6+)
    Both formats are searched and the first match wins.

    @ raw   : str  = full dumpsys telephony.registry output
    -> dict : keys rsrp, rsrq, rssi, snr, ta — all str, empty when absent
    """
    phone0 : str = get_phone0_block(raw)

    # Try the wrapped mLte= format first (most OEMs), then the flat format (Samsung S24+)
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
    Extracts cell identity fields using a unified multi-pattern approach
    that covers all known Android OEM variants without OEM-specific branches.

    Tries multiple field name variants for each value in priority order —
    the first non-empty match wins. Bandwidth falls back to PhysicalChannelConfigs
    when the mBandwidth field holds a sentinel (common on Samsung S24+).

    @ raw          : str  = full dumpsys telephony.registry output
    @ manufacturer : str  = lowercase manufacturer name from getprop
    -> dict        : keys mcc, mnc, tac, eci, earfcn, pci, lteBandwidth, provider
                     — all str, empty when absent
    """
    phone0 : str = get_phone0_block(raw)

    # Isolate the CellIdentityLte block. The S24 uses "CellIdentityLte:{ ... }"
    # (colon-brace style), older OEMs use "mCellIdentity=CellIdentityLte:{ ... }"
    # or "mCellIdentityLTE={ ... }". We try all three block patterns and pick the
    # first match; if none, fall back to searching the whole phone0 block.
    ci_block : str = ""
    for ci_pattern in (
        r"CellIdentityLte[:\s]*\{([^}]+)\}",           # S24 / AOSP flat style
        r"mCellIdentity(?:LTE|Lte|LTE4G)?[=:\s{]+([^}]+)\}",  # older wrapped style
    ):
        m = re.search(ci_pattern, phone0, re.IGNORECASE)
        if m:
            ci_block = m.group(1)
            break

    if not ci_block:
        ci_block = phone0  # last resort — search full block

    # MCC / MNC — try string variants first (MccStr, MncStr), then plain int fields
    mcc : str = clean(first_of(
        ci_block,
        r"mMcc(?:Str)?[=:\s]+(\d+)",
        r"\bmcc[=:\s]+(\d+)",
    ))
    mnc : str = clean(first_of(
        ci_block,
        r"mMnc(?:Str)?[=:\s]+(\d+)",
        r"\bmnc[=:\s]+(\d+)",
    ))

    # Xiaomi / MIUI blocks the TAC and ECI in their modem HAL — flag as hidden
    is_xiaomi : bool = any(b in manufacturer for b in ("xiaomi", "redmi", "poco"))

    tac : str = "hidden" if is_xiaomi else clean(first_of(
        ci_block,
        r"mTac[=:\s]+(\d+)",
        r"\btac[=:\s]+(\d+)",
    ))
    eci : str = "hidden" if is_xiaomi else clean(first_of(
        ci_block,
        r"mCi[=:\s]+(\d+)",
        r"mEci[=:\s]+(\d+)",
        r"\bci[=:\s]+(\d+)",
    ))

    # EARFCN — Samsung S24 stores this under mDownlinkChannelNumber in
    # PhysicalChannelConfigs; also check mChannelNumber (Xiaomi) and mEarfcn (AOSP)
    earfcn : str = clean(first_of(
        ci_block + "\n" + phone0,
        r"mEarfcn[=:\s]+(\d+)",
        r"mChannelNumber[=:\s]+(\d+)",
        r"mDownlinkChannelNumber[=:\s]+(\d+)",
        r"\bearfcn[=:\s]+(\d+)",
    ))

    # PCI — check ci_block first, then PhysicalChannelConfigs (most reliable on S24)
    pci : str = clean(first_of(
        ci_block,
        r"mPci[=:\s]+(\d+)",
        r"mPhysicalCellId[=:\s]+(\d+)",
        r"\bpci[=:\s]+(\d+)",
    ))
    if not pci:
        # Fall back to PrimaryServing block in PhysicalChannelConfigs
        m = re.search(
            r"mConnectionStatus=PrimaryServing[^}]*?mPhysicalCellId=(\d+)", phone0
        )
        pci = clean(m.group(1) if m else "")

    # Bandwidth — S24 reports sentinel in mBandwidth but the real value lives in
    # mCellBandwidthDownlinkKhz inside PhysicalChannelConfigs
    bw_raw : str = clean(first_of(ci_block, r"mBandwidth[=:\s]+(\d+)"))
    if not bw_raw:
        # Try PhysicalChannelConfigs for PrimaryServing component
        m = re.search(
            r"mConnectionStatus=PrimaryServing[^}]*?mCellBandwidthDownlinkKhz=(\d+)",
            phone0
        )
        if m and m.group(1) != str(SENTINEL):
            bw_raw = m.group(1)

    # Provider name
    provider : str = first_of(
        ci_block,
        r"mAlphaLong=([^,\s}]+)",
        r"mOperatorAlphaLong=([^,\s}]+)",
        r"operatorName=([^,\s}]+)",
    )

    if "Digi" in provider:
        provider = "Digi"

    return {
        "mcc"         : mcc,
        "mnc"         : mnc,
        "tac"         : tac,
        "eci"         : eci,
        "earfcn"      : earfcn,
        "pci"         : pci,
        "lteBandwidth": map_bandwidth(bw_raw),
        "provider"    : provider,
    }


def parse_carrier_aggregation(raw: str) -> dict:
    """
    Extracts Carrier Aggregation state from mPhysicalChannelConfigs,
    scoped to Phone Id=0.

    @ raw   : str  = full dumpsys telephony.registry output
    -> dict : keys caEnabled (str 'true'/'false'), caComponents (str count),
              caBandwidthsKhz (str '+'-joined scientific notation) — empty when absent
    """
    phone0 : str = get_phone0_block(raw)

    configs_match = re.search(r"(?:mPhysicalChannelConfigs|PhysicalChannelConfigs)=\[(.+?)\]", phone0, re.DOTALL | re.IGNORECASE)
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
        lat = first_of(block, r"\blat=(-?\d+\.\d+)", r"latitude=(-?\d+\.\d+)", r"mLatitude=(-?\d+\.\d+)")
        lon = first_of(block, r"\blon=(-?\d+\.\d+)", r"longitude=(-?\d+\.\d+)", r"mLongitude=(-?\d+\.\d+)")
        alt = first_of(block, r"\balt=(-?\d+\.\d+)", r"altitude=(-?\d+\.\d+)", r"mAltitude=(-?\d+\.\d+)")
        spd = first_of(block, r"\bvel=(-?\d+\.\d+)", r"speed=(-?\d+\.\d+)", r"mSpeed=(-?\d+\.\d+)")
        acc = first_of(block, r"\bacc=(-?\d+\.\d+)", r"hAcc=(-?\d+\.\d+)", r"accuracy=(-?\d+\.\d+)", r"mAccuracy=(-?\d+\.\d+)")

    return {
        "latitude" : "" if lat in ZERO_VALS else lat,
        "longitude": "" if lon in ZERO_VALS else lon,
        "altitude" : "" if alt in ZERO_VALS else alt,
        "speed"    : "0" if spd in ZERO_VALS else spd,
        "accuracy" : "" if acc in ZERO_VALS else acc,
    }


def parse_location(raw: str, manufacturer: str) -> dict:
    """
    Parses dumpsys location output for any device.
    Delegates field extraction to _parse_location_block.

    @ raw          : str  = output from dumpsys location (grepped block)
    @ manufacturer : str  = lowercase manufacturer name (unused; kept for API compat)
    -> dict        : keys latitude, longitude, altitude, speed, accuracy
                     — all str, empty when absent or GPS not yet locked
    """
    return _parse_location_block(raw)


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

    The file is written with:
      - UTF-8 BOM (utf-8-sig) so Excel opens it correctly without treating
        all columns as one — this is the most reliable fix for older Excel
        versions that ignore the Content-Type and default to the system ANSI page.
      - Explicit comma delimiter (Excel's list separator must match; BOM signals UTF-8
        which locks the delimiter to comma in most locales).

    Progress is printed as [n/m] only — no field data is echoed to stdout.

    @ serial       : str = device serial number
    @ manufacturer : str = lowercase manufacturer name
    -> None
    """
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer : csv.DictWriter = csv.DictWriter(
            f, fieldnames=HEADERS, delimiter=",", quoting=csv.QUOTE_MINIMAL
        )
        write_header(writer)

        count : int = 0
        while count < RUNS:
            row : dict = collect_row(serial, manufacturer)
            write_row(writer, row)
            f.flush()
            count += 1
            print(f"[{count:>{len(str(RUNS))}}/{RUNS} ]")
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