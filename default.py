import xbmc
import xbmcaddon
import xbmcgui

import os
import glob

from resources.lib.workflow_backup import backup_to_b2
from resources.lib.workflow_restore import restore_from_b2
from resources.lib.workflow_backup_local import backup_local
from resources.lib.workflow_restore_local import restore_local
from resources.lib.addon_installer import run_install
from resources.lib.paths import profile
from resources.lib.b2 import B2Client
from resources.lib.log import info, warn, err, exc
from resources.lib.jsonrpc import JsonRpc
from resources.lib.uiwait import wait_for_modal_to_close

ADDON = xbmcaddon.Addon()

def s(id_): return ADDON.getSetting(id_)

def main():
    choices = [
        "Local Backup",
        "Local Restore",
        "Backup to Cloud (B2)",
        "Restore from Cloud (B2)",
        "Settings",
        "Debug JSONRPC"
    ]
    idx = xbmcgui.Dialog().select("Profiler", choices)
    if idx == 0:
        try:
            backup_local()
        except Exception as e:
            exc(f"Restore failed: {e}")
            xbmcgui.Dialog().ok("Error", str(e))
    elif idx == 1:
        try:
            do_local_restore()
        except Exception as e:
            exc(f"Restore failed: {e}")
            xbmcgui.Dialog().ok("Error", str(e))  
    elif idx == 2:
        try:
            do_backup()
        except Exception as e:
            exc(f"Restore failed: {e}")
            xbmcgui.Dialog().ok("Error", str(e)) 
    elif idx == 3:
        try:
            do_restore()
        except Exception as e:
            exc(f"Restore failed: {e}")
            xbmcgui.Dialog().ok("Error", str(e))
    elif idx == 4:
        ADDON.openSettings()
    elif idx == 5:
        debug_jsonrpc()
        
def debug_jsonrpc():
    rpc = JsonRpc()
    schema = rpc.introspect()
    text = str(schema)
    xbmcgui.Dialog().textviewer("JSONRPC schema", text[:100000])

def do_backup():
    name = xbmcgui.Dialog().input("Build name", type=xbmcgui.INPUT_ALPHANUM)
    if not name:
        return

    res = backup_to_b2(
        build_name=name,
        b2_key_id=s("b2_key_id").strip(),
        b2_app_key=s("b2_app_key").strip(),
        b2_bucket=s("b2_bucket_name").strip(),
        b2_prefix=s("b2_prefix").strip(),
        b2_bucket_id=s("b2_bucket_id").strip(),
        include_keymaps=(s("include_keymaps") == "true"),
        include_adv=(s("include_advancedsettings") == "true"),
    )
    xbmcgui.Dialog().ok("Backup complete", f"Uploaded: {res['remote_name']}")

def do_restore():
    ADDON.setSettingBool("restore_in_progress", True)

    b2 = B2Client(s("b2_key_id").strip(), s("b2_app_key").strip())
    b2.authorize()

    bucket_id = s("b2_bucket_id").strip()
    if not bucket_id:
        xbmcgui.Dialog().ok("Profiler", "B2 Bucket ID is missing in settings.")
        ADDON.setSettingBool("restore_in_progress", False)
        return

    prefix = (s("b2_prefix") or "").strip().strip("/")
    listing = b2.list_file_names(bucket_id, prefix=prefix)
    files = [f["fileName"] for f in listing.get("files", []) if f.get("fileName", "").endswith(".zip")]

    if not files:
        xbmcgui.Dialog().ok("No backups found", "Nothing to restore in this bucket/prefix.")
        ADDON.setSettingBool("restore_in_progress", False)
        return

    pick = xbmcgui.Dialog().select("Choose backup", files)
    if pick < 0:
        ADDON.setSettingBool("restore_in_progress", False)
        return

    # Switch to Estuary first + wait for keep-change dialog to be answered
    rpc = JsonRpc()
    rpc.set_setting("lookandfeel.skin", "skin.estuary")

    xbmc.sleep(300)
    ok = wait_for_modal_to_close(timeout_ms=30000)
    if not ok:
        xbmcgui.Dialog().ok("Profiler", "Please confirm the skin change to Estuary, then try again.")
        ADDON.setSettingBool("restore_in_progress", False)
        return

    current_skin = JsonRpc().get_setting("lookandfeel.skin").get("value")
    if current_skin != "skin.estuary":
        xbmcgui.Dialog().ok("Profiler", "Restore cancelled: you must switch to Estuary to continue.")
        ADDON.setSettingBool("restore_in_progress", False)
        return

    # Restore files from B2 zip (now returns manifest)
    manifest = restore_from_b2(
        remote_name=files[pick],
        b2_key_id=s("b2_key_id"),
        b2_app_key=s("b2_app_key"),
        b2_bucket=s("b2_bucket_name"),
        overwrite_xml=(s("overwrite_xml_on_restore") == "true"),
    )

    clear_gui_cache()

    install_report = run_install(manifest)
    fail_count = len(install_report["repos"]["failed"]) + len(install_report["addons"]["failed"])
    ok_count = len(install_report["repos"]["installed"]) + len(install_report["addons"]["installed"])
    skip_count = len(install_report["repos"]["skipped"]) + len(install_report["addons"]["skipped"])

    xbmcgui.Dialog().ok(
        "Profiler",
        f"Install results:\n\n"
        f"Installed: {ok_count}\n"
        f"Skipped: {skip_count}\n"
        f"Failed: {fail_count}\n\n"
        "Next: Restart Kodi + re-authorise Debrid"
    )
    
    if fail_count:
        first = install_report["addons"]["failed"][:5]
        details = "\n".join([f"- {x['id']}: {x['error']}" for x in first])
        xbmcgui.Dialog().ok("Install failures (first 5)", details)


    msg = (
        "Restore complete.\n\n"
        "Kodi will restart into Estuary.\n"
        "After restart, Profiler will prompt you to switch back to your skin.\n\n"
        "Restart Kodi now?"
    )

    if xbmcgui.Dialog().yesno("Profiler", msg):
        ADDON.setSettingBool("pending_finalize", True)
        ADDON.setSettingString("pending_skin", manifest.get("active_skin") or "")

        ADDON.setSettingBool("restore_in_progress", False)

        xbmc.executebuiltin("Dialog.Close(all,true)")
        xbmc.sleep(1200)
        rpc.quit_app()
        xbmc.sleep(1200)
        xbmc.executebuiltin("Quit")
        return

    # User chose not to restart now
    ADDON.setSettingBool("restore_in_progress", False)
    
def do_local_restore():
    ADDON.setSettingBool("restore_in_progress", True)

    backup_dir = profile("addon_data/script.kodi.profiler/backups")
    files = [f for f in os.listdir(backup_dir) if f.lower().endswith(".zip")]
    if not files:
        xbmcgui.Dialog().ok("Local Restore", "No backups found.")
        ADDON.setSettingBool("restore_in_progress", False)
        return

    pick = xbmcgui.Dialog().select("Choose backup", files)
    if pick < 0:
        ADDON.setSettingBool("restore_in_progress", False)
        return

    rpc = JsonRpc()

    # Switch to Estuary first so the target skin doesn't overwrite restored settings
    rpc.set_setting("lookandfeel.skin", "skin.estuary")

    xbmc.sleep(300)
    ok = wait_for_modal_to_close(timeout_ms=30000)
    if not ok:
        xbmcgui.Dialog().ok(
            "Profiler",
            "Please confirm the skin change to Estuary, then run restore again."
        )
        ADDON.setSettingBool("restore_in_progress", False)
        return

    current_skin = JsonRpc().get_setting("lookandfeel.skin").get("value")
    if current_skin != "skin.estuary":
        xbmcgui.Dialog().ok(
            "Profiler",
            "Restore cancelled.\n\nYou must switch to Estuary to continue."
        )
        ADDON.setSettingBool("restore_in_progress", False)
        return

    # Restore files
    manifest = restore_local(files[pick], overwrite_xml=True)

    # Clear GUI cache DBs after restoring settings
    clear_gui_cache()

    # Install repos + addons (repos currently empty in your manifest, but keep it)
    install_report = run_install(manifest)

    repo_fail = len(install_report["repos"]["failed"])
    addon_fail = len(install_report["addons"]["failed"])
    fail_count = repo_fail + addon_fail
    
    if fail_count:
        first = install_report["addons"]["failed"][:5]
        details = "\n".join([f"- {x['id']}: {x['error']}" for x in first])
        xbmcgui.Dialog().ok("Install failures (first 5)", details)


    ok_count = len(install_report["repos"]["installed"]) + len(install_report["addons"]["installed"])
    skip_count = len(install_report["repos"]["skipped"]) + len(install_report["addons"]["skipped"])

    xbmcgui.Dialog().ok(
        "Profiler",
        "Install results:\n\n"
        f"Installed: {ok_count}\n"
        f"Skipped: {skip_count}\n"
        f"Failed: {fail_count}\n\n"
        "Next: Restart Kodi + re-authorise Debrid"
    )

    msg = (
        "Restore complete.\n\n"
        "Kodi will restart into Estuary.\n"
        "On next startup, Profiler will prompt you to switch back to your skin.\n\n"
        "Restart Kodi now?"
    )

    if xbmcgui.Dialog().yesno("Local Restore", msg):
        ADDON.setSettingBool("pending_finalize", True)
        ADDON.setSettingString("pending_skin", manifest.get("active_skin") or "")

        ADDON.setSettingBool("restore_in_progress", False)

        xbmc.executebuiltin("Dialog.Close(all,true)")
        xbmc.sleep(1200)

        rpc.quit_app()
        xbmc.sleep(1200)

        xbmc.executebuiltin("Quit")
        return

    # user chose not to restart
    ADDON.setSettingBool("restore_in_progress", False)
        
def clear_gui_cache():
    db_dir = profile("Database")
    if not os.path.isdir(db_dir):
        return

    for pattern in ("Addons*.db", "ViewModes*.db"):
        for path in glob.glob(os.path.join(db_dir, pattern)):
            try:
                os.remove(path)
            except Exception:
                pass
                

if __name__ == "__main__":
    main()
