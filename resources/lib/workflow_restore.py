import json
import os
import time
import shutil
import xbmc
import xbmcvfs

from resources.lib.jsonrpc import JsonRpc
from resources.lib.paths import profile, temp, home
from resources.lib.fileops import ensure_dir, copy_file
from resources.lib.zipops import unzip_to_dir
from resources.lib.b2 import B2Client
from resources.lib.log import info, warn, err, exc


def _validate_manifest(manifest: dict):
    if not isinstance(manifest, dict):
        raise RuntimeError("Manifest is not an object")

    if "repos" not in manifest or "addons" not in manifest:
        raise RuntimeError("Manifest missing required keys: repos/addons")

    repos = manifest.get("repos")
    addons = manifest.get("addons")

    if not isinstance(repos, list):
        raise RuntimeError("Manifest repos must be a list")
    if not isinstance(addons, list):
        raise RuntimeError("Manifest addons must be a list")

    for r in repos:
        if not isinstance(r, dict):
            raise RuntimeError("Manifest repos must contain dict entries only")
        if not r.get("id"):
            raise RuntimeError("Repo entry missing id")
        r.setdefault("zip_in_backup", "")
        r.setdefault("zip_url", "")
        r.setdefault("zip_path", "")

    for a in addons:
        if not isinstance(a, str):
            raise RuntimeError("Manifest addons must be strings")
        if a.startswith("repository."):
            raise RuntimeError("Manifest addons must not contain repository.* IDs")


def _install_repo_from_backup_zip(repo_id: str, zip_abs_path: str, timeout_s: int = 60):
    """
    Install repo by:
    1) copy zip into special://home/addons/packages/
    2) InstallAddon(repo_id)
    3) wait until special://home/addons/<repo_id>/ appears
    """
    packages_dir = home("addons/packages")
    ensure_dir(packages_dir)

    # copy zip into packages with its filename
    dst_zip = os.path.join(packages_dir, os.path.basename(zip_abs_path))
    copy_file(zip_abs_path, dst_zip)
    info(f"Repo zip copied to packages: {repo_id} -> {dst_zip}")

    # Install by ID (silent)
    info(f"Installing repo via InstallAddon(id): {repo_id}", notify=True)
    xbmc.executebuiltin(f"InstallAddon({repo_id})")

    # Wait for extracted folder
    addon_dir = home(f"addons/{repo_id}")
    start = time.time()
    while time.time() - start < timeout_s:
        if os.path.isdir(addon_dir):
            info(f"Repo installed OK (folder appeared): {repo_id}")
            return True
        xbmc.sleep(1000)

    err(f"Repo install failed (folder never appeared): {repo_id}", notify=True)
    return False


def restore_from_b2(remote_name: str, b2_key_id: str, b2_app_key: str, b2_bucket: str, overwrite_xml: bool):
    info(f"Restore start: remote={remote_name}", notify=True)

    zip_path = temp("profiler/incoming/restore.zip")
    ensure_dir(os.path.dirname(zip_path))

    b2 = B2Client(b2_key_id.strip(), b2_app_key.strip())
    b2.authorize()
    info("Downloading backup from B2…", notify=True)
    data = b2.download_by_name(b2_bucket.strip(), remote_name)

    with open(zip_path, "wb") as f:
        f.write(data)
    info(f"Downloaded {len(data)} bytes to {zip_path}")

    staging = temp("profiler/restore_staging")

    # clean staging each run to avoid stale files
    if os.path.isdir(staging):
        try:
            shutil.rmtree(staging)
        except Exception:
            warn("Could not fully wipe staging dir; continuing")

    ensure_dir(staging)
    info(f"Unzipping backup to {staging}", notify=True)
    unzip_to_dir(zip_path, staging)

    user_stage = os.path.join(staging, "userdata")

    # Copy key XML files
    for name in ["sources.xml", "guisettings.xml", "favourites.xml", "advancedsettings.xml"]:
        src = os.path.join(user_stage, name)
        dst = profile(name)
        if os.path.exists(src):
            if overwrite_xml or not xbmcvfs.exists(dst):
                info(f"Restore file: {name}")
                copy_file(src, dst)
            else:
                info(f"Skip existing XML (overwrite disabled): {name}")

    # Copy portable dirs
    for d in ["addon_data", "keymaps"]:
        src_root = os.path.join(user_stage, d)
        if os.path.isdir(src_root):
            dst_root = profile(d)
            ensure_dir(dst_root)

            info(f"Restore dir: {d}")
            for root, _, files in os.walk(src_root):
                rel = os.path.relpath(root, src_root)
                out_dir = dst_root if rel == "." else os.path.join(dst_root, rel)
                ensure_dir(out_dir)
                for fn in files:
                    copy_file(os.path.join(root, fn), os.path.join(out_dir, fn))

    # Load manifest
    manifest_path = os.path.join(staging, "manifest.json")
    if not os.path.exists(manifest_path):
        raise RuntimeError("manifest.json missing from backup zip")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    _validate_manifest(manifest)

    # Resolve repo zips + install repos NOW (so addons can resolve)
    repos = manifest.get("repos", [])

    for repo in repos:
        rid = repo["id"]

        # safety: never attempt xbmc built-in repo
        if rid.startswith("repository.xbmc"):
            info(f"Skip built-in repo: {rid}")
            continue

        rel = (repo.get("zip_in_backup") or "").strip()
        repo["zip_path"] = ""

        if not rel:
            warn(f"Repo has no zip_in_backup: {rid}")
            continue

        abs_zip = os.path.join(staging, rel.replace("/", os.sep))
        if not os.path.isfile(abs_zip):
            err(f"Repo zip missing in backup for {rid}: expected {abs_zip}", notify=True)
            continue

        repo["zip_path"] = abs_zip
        info(f"Repo zip resolved: {rid} -> {abs_zip}")

        ok = _install_repo_from_backup_zip(rid, abs_zip, timeout_s=60)
        if not ok:
            # Don’t hard stop; keep going so you get a full report
            warn(f"Repo install failed: {rid}. Addons depending on it may fail.", notify=True)

        # small delay to reduce DB thrash on Firestick
        xbmc.sleep(2000)

    # After repo installs, refresh repo data
    rpc = JsonRpc()
    rpc.update_addon_repos()
    xbmc.sleep(8000)

    info("Restore staging complete; returning manifest", notify=True)
    return manifest
