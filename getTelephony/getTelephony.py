import csv
import time
from adb_utils import get_serial, get_manufacturer
from collector import collect_row
from constants import OUTPUT_FILE, INTERVAL_SEC, RUNS, HEADERS, XIAOMI_BRANDS


def run_loop(serial: str, manufacturer: str) -> None:
    """
    Main collection loop. Writes CSV header once, then collects RUNS rows
    at INTERVAL_SEC cadence, flushing after each write.

    @ serial       : str = device serial number
    @ manufacturer : str = lowercase manufacturer name
    -> None
    """
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer : csv.DictWriter = csv.DictWriter(f, fieldnames=HEADERS, delimiter=",", quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()

        for count in range(1, RUNS + 1):
            writer.writerow(collect_row(serial, manufacturer))
            f.flush()
            print(f"[{count:>{len(str(RUNS))}}/{RUNS}]")
            if count < RUNS:
                time.sleep(INTERVAL_SEC)

    print(f"\nDone — {RUNS} records saved to {OUTPUT_FILE}")


def main() -> None:
    """
    Entry point. Detects device, runs a preflight check, then starts the loop.

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
    if any(b in manufacturer for b in XIAOMI_BRANDS):
        expected_empty.update({"tac", "eci"})

    missing : list[str] = [k for k, v in diag.items() if v in ("", None) and k not in expected_empty]

    if missing:
        print(f"WARNING  : missing fields — {', '.join(missing)}\n")
    else:
        print("OK       : all expected fields populated\n")

    run_loop(serial, manufacturer)


if __name__ == "__main__":
    main()