import xbmc
import xbmcgui
import time
import traceback

ADDON_ID = "script.kodi.profiler"

# Map to Kodi notification icons
_ICON_INFO = xbmcgui.NOTIFICATION_INFO
_ICON_WARN = xbmcgui.NOTIFICATION_WARNING
_ICON_ERR = xbmcgui.NOTIFICATION_ERROR


def _ts():
    # readable timestamp in log output
    return time.strftime("%Y-%m-%d %H:%M:%S")


def log(msg, level=xbmc.LOGINFO, notify=False, notify_level="info"):
    """
    Central logger.
    - level: xbmc.LOGINFO / xbmc.LOGWARNING / xbmc.LOGERROR / xbmc.LOGDEBUG
    - notify: show Kodi notification
    - notify_level: info|warn|error (controls notification icon)
    """
    line = f"[Profiler] {_ts()} {msg}"
    xbmc.log(line, level)

    if notify:
        icon = _ICON_INFO
        if notify_level == "warn":
            icon = _ICON_WARN
        elif notify_level == "error":
            icon = _ICON_ERR

        xbmcgui.Dialog().notification(
            "Profiler",
            msg,
            icon,
            5000
        )


def info(msg, notify=False):
    log(msg, xbmc.LOGINFO, notify=notify, notify_level="info")


def warn(msg, notify=False):
    log(msg, xbmc.LOGWARNING, notify=notify, notify_level="warn")


def err(msg, notify=False):
    log(msg, xbmc.LOGERROR, notify=notify, notify_level="error")


def exc(msg, notify=True):
    """
    Log exception + traceback.
    Call inside except blocks.
    """
    tb = traceback.format_exc()
    log(f"{msg}\n{tb}", xbmc.LOGERROR, notify=notify, notify_level="error")
