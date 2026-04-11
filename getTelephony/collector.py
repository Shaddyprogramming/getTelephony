from datetime import datetime
from adb_utils import get_telephony_dump, get_location_dump
from parsers import parse_lte_signal, parse_cell_identity, parse_carrier_aggregation, parse_location


_prev_pci  : str = ""
_prev_rsrp : str = ""


def compute_l2_events(current_pci: str, current_rsrp: str) -> dict:
    """
    Derives L2 mobility events by comparing current values to the previous sample.

    @ current_pci  : str  = Physical Cell ID of the current measurement
    @ current_rsrp : str  = RSRP of the current measurement
    -> dict        : keys cellChangeDetected (str 'true'/'false'),
                     signalDeltaRsrp (str int) — empty on the first sample
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

    return {"cellChangeDetected": cell_change, "signalDeltaRsrp": delta_rsrp}


def collect_row(serial: str, manufacturer: str) -> dict:
    """
    Collects one full measurement row from the device.

    @ serial       : str  = device serial number
    @ manufacturer : str  = lowercase manufacturer name
    -> dict        : complete row with all HEADERS keys populated,
                     empty string where data is unavailable
    """
    raw_registry : str = get_telephony_dump()
    raw_location : str = get_location_dump()
    timestamp    : str = datetime.now().astimezone().isoformat()

    signal   : dict = parse_lte_signal(raw_registry)
    identity : dict = parse_cell_identity(raw_registry, manufacturer)
    ca       : dict = parse_carrier_aggregation(raw_registry)
    location : dict = parse_location(raw_location)
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