import os
import sys

import xbmc
import xbmcaddon
import xbmcgui

ADDON = xbmcaddon.Addon()

# Ensure this add-on's lib folder is on sys.path
LIB_PATH = os.path.join(ADDON.getAddonInfo("path"), "resources", "lib")
if LIB_PATH not in sys.path:
    sys.path.insert(0, LIB_PATH)

from jsonrpc import JsonRpc

def run():
    xbmc.log("[ProfilerService] starting", xbmc.LOGINFO)
    
    monitor = xbmc.Monitor()
    for _ in range(10):  # ~3s
        if monitor.abortRequested():
            return
        xbmc.sleep(300)

    # Do NOT run during an active restore session
    if ADDON.getSettingBool("restore_in_progress"):
        xbmc.log("[ProfilerService] restore_in_progress=True, skipping", xbmc.LOGINFO)
        return

    pending = ADDON.getSettingBool("pending_finalize")
    skin = ADDON.getSettingString("pending_skin")
    xbmc.log(f"[ProfilerService] pending_finalize={pending} pending_skin={skin}", xbmc.LOGINFO)

    if not pending:
        return

    msg = (
        "Restore completed.\n\n"
        f"Switch back to your skin now?\n\n{skin}\n\n"
        "Kodi may ask “Keep this change?” — press YES."
    )

    if xbmcgui.Dialog().yesno("Profiler", msg):
        JsonRpc().set_setting("lookandfeel.skin", skin)

    ADDON.setSettingBool("pending_finalize", False)
    ADDON.setSettingString("pending_skin", "")
    xbmc.log("[ProfilerService] cleared pending flags", xbmc.LOGINFO)

if __name__ == "__main__":
    run()
