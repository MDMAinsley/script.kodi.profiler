import json
import os
import xbmcvfs

from resources.lib.paths import profile, temp
from resources.lib.fileops import ensure_dir, copy_file
from resources.lib.zipops import unzip_to_dir
from resources.lib.b2 import B2Client

def restore_from_b2(remote_name: str, b2_key_id: str, b2_app_key: str, b2_bucket: str, overwrite_xml: bool):
    zip_path = temp("profiler/incoming/restore.zip")
    ensure_dir(os.path.dirname(zip_path))

    b2 = B2Client(b2_key_id.strip(), b2_app_key.strip())
    b2.authorize()
    data = b2.download_by_name(b2_bucket.strip(), remote_name)
    with open(zip_path, "wb") as f:
        f.write(data)

    staging = temp("profiler/restore_staging")
    ensure_dir(staging)
    unzip_to_dir(zip_path, staging)

    user_stage = os.path.join(staging, "userdata")

    for name in ["sources.xml", "guisettings.xml", "favourites.xml", "advancedsettings.xml"]:
        src = os.path.join(user_stage, name)
        dst = profile(name)
        if os.path.exists(src):
            if overwrite_xml or not xbmcvfs.exists(dst):
                copy_file(src, dst)

    for d in ["addon_data", "keymaps"]:
        src_root = os.path.join(user_stage, d)
        if os.path.isdir(src_root):
            dst_root = profile(d)
            ensure_dir(dst_root)
            for root, _, files in os.walk(src_root):
                rel = os.path.relpath(root, src_root)
                out_dir = dst_root if rel == "." else os.path.join(dst_root, rel)
                ensure_dir(out_dir)
                for fn in files:
                    copy_file(os.path.join(root, fn), os.path.join(out_dir, fn))

    manifest_path = os.path.join(staging, "manifest.json")
    if not os.path.exists(manifest_path):
        raise RuntimeError("manifest.json missing from backup zip")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
        
    repos_dir = os.path.join(staging, "repos")
    for repo in manifest.get("repos", []):
        rel = repo.get("zip_in_backup") or ""
        if rel:
            abs_zip = os.path.join(staging, rel.replace("/", os.sep))
            repo["zip_path"] = abs_zip

    return manifest
