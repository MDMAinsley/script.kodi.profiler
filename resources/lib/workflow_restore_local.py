import os
import json
import xbmc

from resources.lib.paths import profile, temp
from resources.lib.fileops import ensure_dir, copy_file
from resources.lib.zipops import unzip_to_dir
from resources.lib.jsonrpc import JsonRpc

def restore_local(zip_filename: str, overwrite_xml: bool = True):
    backup_dir = profile("addon_data/script.kodi.profiler/backups")
    zip_path = os.path.join(backup_dir, zip_filename)

    staging = temp("profiler/restore_staging")
    ensure_dir(staging)

    unzip_to_dir(zip_path, staging)

    user_stage = os.path.join(staging, "userdata")

    # Restore XMLs if present
    for name in ["guisettings.xml", "sources.xml", "favourites.xml", "advancedsettings.xml"]:
        src = os.path.join(user_stage, name)
        dst = profile(name)
        if os.path.exists(src):
            if overwrite_xml or (not os.path.exists(dst)):
                copy_file(src, dst)

    # Restore addon_data (merge)
    src_addon_data = os.path.join(user_stage, "addon_data")
    if os.path.isdir(src_addon_data):
        dst_addon_data = profile("addon_data")
        ensure_dir(dst_addon_data)

        for root, _, files in os.walk(src_addon_data):
            rel = os.path.relpath(root, src_addon_data)
            out_dir = dst_addon_data if rel == "." else os.path.join(dst_addon_data, rel)
            ensure_dir(out_dir)
            for fn in files:
                copy_file(os.path.join(root, fn), os.path.join(out_dir, fn))

    # Load manifest so we can show it (install step comes later)
    manifest_path = os.path.join(staging, "manifest.json")
    manifest = {}
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)     

    return manifest
    