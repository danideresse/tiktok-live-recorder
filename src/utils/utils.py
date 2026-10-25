import json
import os

from utils.enums import Info


def banner() -> None:
    """
    Prints a banner with the name of the tool and its version number.
    """
    print(Info.BANNER, flush=True)


def read_cookies():
    """
    Loads the config file and returns it.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "..", "cookies.json")
    with open(config_path, "r") as f:
        data = json.load(f)
    if isinstance(data, list):
        extracted = {}
        for item in data:
            if isinstance(item, dict) and "name" in item and "value" in item:
                extracted[item["name"]] = item["value"]
        data = extracted

    # Filter out volatile/ephemeral WAF tokens that trigger TikTok 429
    bad_keys = {
        "_waftokenid",
        "waforigin_id",
        "waforiginalreid",
        "s_v_web_id",
        "perf_feed_cache",
        "delay_guest_mode_vid",
        "living_user_id",
        "passport_fe_beating_status",
    }
    return {k: v for k, v in data.items() if k not in bad_keys and v}




def read_telegram_config():
    """
    Loads the telegram config file and returns it.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "..", "telegram.json")
    with open(config_path, "r") as f:
        return json.load(f)


def is_termux() -> bool:
    """
    Checks if the script is running in Termux.

    Returns:
        bool: True if running in Termux, False otherwise.
    """
    import distro
    import platform

    return platform.system().lower() == "linux" and distro.like() == ""


def is_windows() -> bool:
    """
    Checks if the script is running on Windows.

    Returns:
        bool: True if running on Windows, False otherwise.
    """
    import platform

    return platform.system().lower() == "windows"


def is_linux() -> bool:
    """
    Checks if the script is running on Linux.

    Returns:
        bool: True if running on Linux, False otherwise.
    """
    import platform

    return platform.system().lower() == "linux"
