import xbmc
import xbmcaddon
import xbmcgui

import os
from resources.lib.workflow_backup import backup_to_b2  # reuse logic
from resources.lib.paths import profile
from resources.lib.fileops import ensure_dir

def backup_local():
    build_name = xbmcgui.Dialog().input("Build name", type=xbmcgui.INPUT_ALPHANUM)
    if not build_name:
        return
        
    backup_dir = profile("addon_data/script.kodi.profiler/backups")
    ensure_dir(backup_dir)

    # reuse backup logic but stop before upload
    result = backup_to_b2(
        build_name=build_name,
        b2_key_id="",
        b2_app_key="",
        b2_bucket="",
        b2_prefix="",
        b2_bucket_id="",
        include_keymaps=True,
        include_adv=False,
        do_upload=False,   # <-- IMPORTANT
    )


    # move zip into local backup dir
    src_zip = result["zip"]
    dst_zip = os.path.join(backup_dir, f"{build_name}.zip")

    import xbmcvfs
    xbmcvfs.copy(src_zip, dst_zip)

    return dst_zip
