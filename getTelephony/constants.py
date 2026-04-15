OUTPUT_FILE  : str   = "lte_data.csv"
INTERVAL_SEC : float = 0.5
RUNS         : int   = 10

SENTINEL : int = 2147483647

HEADERS : list = [
    "deviceTime",
    "mcc", "mnc", "tac", "eci", "eNB_ID", "Cell_ID", "earfcn", "pci",
    "rsrp", "rsrq", "rssi", "snr", "ta",
    "provider", "servingCell", "lteBandwidth",
    "caEnabled", "caComponents", "caBandwidthsKhz",
    "cellChangeDetected", "signalDeltaRsrp",
    "latitude", "longitude", "altitude", "speed", "accuracy",
    "deviceSerialNumber",
]

PROVIDER_ALIASES : dict = {
    "digi"            : "Digi",
    "orange"          : "Orange",
    "vodafone"        : "Vodafone",
    "telekom"         : "Telekom",
    "t-mobile"        : "Telekom",
    "deutsche telekom": "Telekom",
    "o2"              : "O2",
    "at&t"            : "AT&T",
    "att"             : "AT&T",
    "verizon"         : "Verizon",
    "t mobile"        : "T-Mobile",
    "tmobile"         : "T-Mobile",
    "three"           : "Three",
    "ee"              : "EE",
    "bt"              : "BT",
    "claro"           : "Claro",
    "movistar"        : "Movistar",
    "telenor"         : "Telenor",
    "telia"           : "Telia",
    "swisscom"        : "Swisscom",
    "proximus"        : "Proximus",
    "base"            : "Base",
    "bouygues"        : "Bouygues",
    "sfr"             : "SFR",
    "free"            : "Free",
    "wind"            : "Wind",
    "tim"             : "TIM",
    "cosmote"         : "Cosmote",
    "mts"             : "MTS",
    "megafon"         : "MegaFon",
    "beeline"         : "Beeline",
}

RESTRICTED_BRANDS : tuple = ("xiaomi", "redmi", "poco")