import subprocess


def run_adb(command: str, timeout: int = 12) -> str:
    """
    Runs an adb shell command and returns stdout.

    @ command : str = shell command to run
    @ timeout : int = max seconds to wait
    -> str    : raw stdout, or empty string on failure
    """
    try:
        result = subprocess.run(
            ["adb", "shell", command],
            capture_output=True, text=True, timeout=timeout
        )
        return result.stdout
    except Exception:
        return ""


def get_serial() -> str:
    """
    Retrieves the ADB device serial number.

    -> str : serial number, or empty string on failure
    """
    try:
        result = subprocess.run(
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
    return run_adb("getprop ro.product.manufacturer").strip().lower()


def get_telephony_dump() -> str:
    """
    Fetches the full dumpsys telephony.registry output.

    -> str : raw dumpsys output
    """
    return run_adb("dumpsys telephony.registry")


def get_location_dump() -> str:
    """
    Fetches the last known location block from dumpsys location.

    -> str : raw location block output
    """
    return run_adb("dumpsys location | grep -A 5 'last location'")