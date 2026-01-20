import xbmc
import xbmcvfs
import json
import os
import glob

from resources.lib.fileops import ensure_dir, copy_file, walk_dir
from resources.lib.manifest import build_manifest
from resources.lib.zipops import zip_from_dir
from resources.lib.b2 import B2Client
from resources.lib.log import info, warn, err, exc
from resources.lib.paths import profile, temp, home


PORTABLE_FILES = [
    "sources.xml",
    "guisettings.xml",
    "favourites.xml",
]

PORTABLE_DIRS = [
    "addon_data",
]

def backup_to_b2(build_name: str, b2_key_id: str, b2_app_key: str, b2_bucket: str, b2_prefix: str, b2_bucket_id: str, include_keymaps: bool, include_adv: bool, do_upload: bool = True):
    # 1) staging dir
    staging = temp(f"profiler/staging/{build_name}")
    ensure_dir(staging)

    # 2) copy portable files
    user_stage = os.path.join(staging, "userdata")
    ensure_dir(user_stage)

    for f in PORTABLE_FILES:
        src = profile(f)
        info(f"FILE src={src} exists={os.path.exists(src)}")
        if xbmcvfs.exists(src):
            dst = os.path.join(user_stage, f)
            copy_file(src, dst)

    # keymaps optional
    if include_keymaps and xbmcvfs.exists(profile("keymaps")):
        PORTABLE_DIRS_LOCAL = PORTABLE_DIRS + ["keymaps"]
    else:
        PORTABLE_DIRS_LOCAL = PORTABLE_DIRS

    # advancedsettings optional
    if include_adv and xbmcvfs.exists(profile("advancedsettings.xml")):
        copy_file(profile("advancedsettings.xml"), os.path.join(user_stage, "advancedsettings.xml"))

    # 3) copy portable dirs (merge into staging)
    for d in PORTABLE_DIRS_LOCAL:
        src_root = profile(d)
        info(f"DIR src={src_root} exists={os.path.exists(src_root)}")
        if not os.path.isdir(src_root):
            continue
        dst_root = os.path.join(user_stage, d)
        ensure_dir(dst_root)
        
        for root, _, files in os.walk(src_root):
            rel = os.path.relpath(root, src_root)
            out_dir = dst_root if rel == "." else os.path.join(dst_root, rel)
            ensure_dir(out_dir)
            for fn in files:
                copy_file(os.path.join(root, fn), os.path.join(out_dir, fn))

    # 4) manifest + report
    manifest = build_manifest()
    repos_stage = os.path.join(staging, "repos")
    ensure_dir(repos_stage)

    for repo in manifest.get("repos", []):
        rid = repo["id"]

        # Try C1: grab the zip Kodi originally downloaded
        src_zip = _find_latest_repo_zip_in_packages(rid)

        if src_zip and os.path.isfile(src_zip):
            out_name = os.path.basename(src_zip)
            dst_zip = os.path.join(repos_stage, out_name)
            info(f"Repo zip (packages) {rid}: {src_zip} -> {dst_zip}")
            copy_file(src_zip, dst_zip)
            repo["zip_in_backup"] = f"repos/{out_name}"
            repo["zip_url"] = ""
            continue

        # Fallback C1b: build a zip from installed repo folder
        out_name = f"{rid}.zip"
        dst_zip = os.path.join(repos_stage, out_name)
        info(f"Repo zip (generated) {rid}: {dst_zip}")
        _zip_installed_repo_folder(rid, dst_zip)
        repo["zip_in_backup"] = f"repos/{out_name}"
        repo["zip_url"] = ""

    with open(os.path.join(staging, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    report = {"notes": ["Debrid services will usually require re-authorization on the new device."]}
    with open(os.path.join(staging, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    # 5) zip
    out_zip = temp(f"profiler/out/{build_name}.zip")
    ensure_dir(os.path.dirname(out_zip))
    zip_from_dir(staging, out_zip)

    # 6) upload to B2
    if do_upload:
        b2 = B2Client(b2_key_id, b2_app_key)
        b2.authorize()
        if not b2_bucket_id:
            raise RuntimeError("B2 Bucket ID is required (your key cannot list buckets). Add it in Profiler settings.")

        up = b2.get_upload_url(b2_bucket_id)
        with open(out_zip, "rb") as f:
            data = f.read()

        remote_name = (b2_prefix or "").rstrip("/") + f"/{build_name}.zip"
        remote_name = remote_name.lstrip("/")
        b2.upload_file(up["uploadUrl"], up["authorizationToken"], remote_name, data)
        return {"zip": out_zip, "remote_name": remote_name, "manifest": manifest}

    # local-only return
    return {"zip": out_zip, "remote_name": "", "manifest": manifest}

def _find_latest_repo_zip_in_packages(repo_id: str) -> str:
    """
    Looks for the repo zip Kodi downloaded previously:
    special://home/addons/packages/<repoid>-*.zip
    Returns file path or "".
    """
    pkg_dir = home("addons/packages")
    pattern = os.path.join(pkg_dir, f"{repo_id}-*.zip")
    matches = sorted(glob.glob(pattern), key=lambda p: os.path.getmtime(p), reverse=True)
    return matches[0] if matches else ""

def _zip_installed_repo_folder(repo_id: str, out_zip: str):
    """
    Fallback: zip the installed repo add-on folder.
    special://home/addons/<repo_id>/
    """
    src_dir = home(f"addons/{repo_id}")
    if not os.path.isdir(src_dir):
        raise RuntimeError(f"Repo folder not found for {repo_id}: {src_dir}")
    zip_from_dir(src_dir, out_zip)