import os
import time
import shutil
import xbmc
import xbmcgui
import xbmcvfs
import urllib.request

from resources.lib.jsonrpc import JsonRpc
from resources.lib.log import info, warn, err, exc
from resources.lib.paths import temp, home

BUILTIN_REPOS = {"repository.xbmc.org"}


# ----------------------------
# Helpers
# ----------------------------

def _sleep(ms: int):
    xbmc.sleep(ms)

def _kodi_path(path: str) -> str:
    """
    Ensure we always pass Kodi-native paths around.
    home("addons") etc already returns real paths on Android,
    but keep this for clarity.
    """
    return path

def _exists(path: str) -> bool:
    """
    On Android, xbmcvfs.exists is more reliable than os.path.exists
    for Kodi-controlled paths.
    """
    return xbmcvfs.exists(path)

def _mkdirs(path: str):
    if not _exists(path):
        xbmcvfs.mkdirs(path)

def _safe_rmtree(path: str):
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
    except Exception as e:
        warn(f"Failed to remove folder {path}: {e}")

def _wait_for_addon_folder(addon_id: str, timeout_s: int = 60) -> bool:
    """
    Wait until special://home/addons/<addon_id>/addon.xml exists.
    This is a REAL confirmation that the repo is installed locally.
    """
    addon_xml = home(f"addons/{addon_id}/addon.xml")
    start = time.time()

    while time.time() - start < timeout_s:
        if _exists(addon_xml):
            return True
        _sleep(500)

    return False


# ----------------------------
# Repo install (Android-safe)
# ----------------------------

def install_repo_zip_by_extract(repo_id: str, zip_path: str, timeout_s: int = 60) -> bool:
    """
    Android/Firestick reliable repo installation:
    1) Delete existing addon folder
    2) Extract zip into special://home/addons/
       using Kodi's built-in Extract()
    3) UpdateLocalAddons (force Kodi to rescan local addon dirs)
    4) EnableAddon(repo_id)
    """
    addons_dir = home("addons")
    dest_dir = os.path.join(addons_dir, repo_id)

    info(f"[RepoExtract] Installing repo: {repo_id} zip={zip_path}", notify=True)

    if not os.path.isfile(zip_path):
        err(f"[RepoExtract] Repo zip missing: {zip_path}", notify=True)
        return False

    # Remove any existing folder
    _safe_rmtree(dest_dir)

    # Ensure addons dir exists
    _mkdirs(addons_dir)

    # Use Kodi built-in Extract(archive, destination)
    # NOTE: destination MUST be an absolute path (home(...) already is)
    try:
        cmd = f'Extract("{zip_path}","{addons_dir}")'
        info(f"[RepoExtract] builtin: {cmd}")
        xbmc.executebuiltin(cmd)
    except Exception as e:
        err(f"[RepoExtract] Extract builtin failed: {e}", notify=True)
        return False

    # Let filesystem settle (Android can be slow)
    _sleep(1500)

    # Force Kodi to rescan local addons
    xbmc.executebuiltin("UpdateLocalAddons")
    _sleep(2000)

    # Wait for addon.xml to appear
    if not _wait_for_addon_folder(repo_id, timeout_s=timeout_s):
        err(f"[RepoExtract] Repo install failed (addon.xml never appeared): {repo_id}", notify=True)
        return False

    # Enable the repo addon (harmless if already enabled)
    xbmc.executebuiltin(f'EnableAddon({repo_id})')
    _sleep(500)

    info(f"[RepoExtract] Repo OK: {repo_id}", notify=True)
    return True


def _download_to(url: str, dst_path: str):
    """
    Download url -> dst_path (binary). Raises on failure.
    Uses urllib (works on Kodi Python).
    """
    info(f"Downloading: {url} -> {dst_path}", notify=True)
    _mkdirs(os.path.dirname(dst_path))

    with urllib.request.urlopen(url, timeout=60) as r:
        with open(dst_path, "wb") as f:
            while True:
                chunk = r.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)

    if not os.path.isfile(dst_path) or os.path.getsize(dst_path) < 1024:
        raise RuntimeError(f"Downloaded file looks wrong: {dst_path}")


def _preflight_or_die(rpc: JsonRpc):
    """
    Preflight: if the addon DB is broken, installed-addon queries can throw.
    """
    try:
        rpc.get_installed_addons()
        info("Addon system preflight OK")
    except Exception:
        exc("Addon system preflight failed (Addons.GetAddons). Addon DB may be broken.")
        raise


def _wait_until_installed_by_list(rpc: JsonRpc, addon_id: str, timeout_s: int = 45):
    """
    Firestick-safe: poll Addons.GetAddons(installed=True) and check for addonid.
    """
    start = time.time()
    last_log = 0

    while True:
        elapsed = int(time.time() - start)
        if elapsed >= timeout_s:
            return False, f"Timed out after {timeout_s}s"

        if elapsed - last_log >= 5:
            info(f"Waiting for install: {addon_id} ({elapsed}s/{timeout_s}s)")
            last_log = elapsed

        try:
            installed_ids = rpc.get_installed_ids()
            if addon_id in installed_ids:
                info(f"Installed (detected via list): {addon_id}")
                return True, ""
        except Exception as e:
            warn(f"GetAddons failed while waiting for {addon_id}: {e}")

        _sleep(1000)


def _validate_manifest(manifest: dict):
    repos = manifest.get("repos")
    addons = manifest.get("addons")

    if not isinstance(repos, list):
        raise RuntimeError("Manifest invalid: repos must be a list of dicts")

    for r in repos:
        if not isinstance(r, dict):
            raise RuntimeError("Manifest invalid: repos must contain dict entries only")
        if not r.get("id"):
            raise RuntimeError("Manifest invalid: repo entry missing id")
        r.setdefault("zip_path", "")
        r.setdefault("zip_url", "")

    if not isinstance(addons, list):
        raise RuntimeError("Manifest invalid: addons must be a list")
    for a in addons:
        if not isinstance(a, str):
            raise RuntimeError("Manifest invalid: addons must be strings")
        if a.startswith("repository."):
            raise RuntimeError("Manifest invalid: addons list must not contain repository.* IDs")


def _install_repos(repo_entries, timeout_per_repo_s: int = 90):
    """
    NEW BEHAVIOUR:
    - Repo installation is ALWAYS done by extracting zip into addons folder.
    - No InstallFromZip
    - No InstallAddon(id) for repos
    """
    rpc = JsonRpc()
    _preflight_or_die(rpc)

    installed_ids = rpc.get_installed_ids()

    installed, skipped, failed = [], [], []

    dialog = xbmcgui.DialogProgress()
    dialog.create("Profiler", "Installing repositories…")

    try:
        total = len(repo_entries) or 1

        for i, repo in enumerate(repo_entries, start=1):
            if dialog.iscanceled():
                warn("User cancelled repo install phase", notify=True)
                failed.append({"id": repo.get("id", ""), "error": "User cancelled"})
                break

            rid = repo["id"]
            zip_path = (repo.get("zip_path") or "").strip()
            zip_url = (repo.get("zip_url") or "").strip()

            pct = int((i / total) * 100)
            dialog.update(pct, f"Repo ({i}/{total}): {rid}")

            # Skip built-in repo id
            if rid in BUILTIN_REPOS and not zip_path and not zip_url:
                info(f"Skip built-in repo: {rid}")
                skipped.append(rid)
                continue

            # If already installed and folder exists, skip
            if rid in installed_ids and _exists(home(f"addons/{rid}/addon.xml")):
                info(f"Skip repo (already installed): {rid}")
                skipped.append(rid)
                continue

            try:
                # Prefer zip from backup
                local_zip = ""
                if zip_path:
                    local_zip = zip_path
                    info(f"Repo zip resolved: {rid} -> {local_zip}", notify=True)

                # Fallback to zip_url
                elif zip_url:
                    local_zip = temp(f"profiler_repo_zips/{rid}.zip")
                    info(f"Repo zip_url fallback: {rid} -> {zip_url}", notify=True)
                    _download_to(zip_url, local_zip)

                else:
                    err(f"Repo has no zip_path or zip_url: {rid}", notify=True)
                    failed.append({"id": rid, "error": "Missing zip_path and zip_url"})
                    continue

                ok = install_repo_zip_by_extract(rid, local_zip, timeout_s=timeout_per_repo_s)
                if ok:
                    installed.append(rid)
                    installed_ids.add(rid)
                else:
                    failed.append({"id": rid, "error": "Extract install failed"})

            except Exception as e:
                exc(f"Exception installing repo {rid}: {e}")
                failed.append({"id": rid, "error": str(e)})

        # After all repos, refresh repo contents ONCE (less DB spam)
        xbmc.executebuiltin("UpdateAddonRepos")
        _sleep(8000)

        return installed, skipped, failed

    finally:
        dialog.close()


def _install_addons(addon_ids, timeout_per_addon_s: int = 60):
    """
    Addons still install by ID using your JsonRpc wrapper (which should fall back to InstallAddon builtin).
    """
    rpc = JsonRpc()
    _preflight_or_die(rpc)

    installed_ids = rpc.get_installed_ids()

    installed, skipped, failed = [], [], []

    dialog = xbmcgui.DialogProgress()
    dialog.create("Profiler", "Installing add-ons…")

    try:
        total = len(addon_ids) or 1

        for i, aid in enumerate(addon_ids, start=1):
            if dialog.iscanceled():
                warn("User cancelled add-on install phase", notify=True)
                failed.append({"id": aid, "error": "User cancelled"})
                break

            pct = int((i / total) * 100)
            dialog.update(pct, f"Addon ({i}/{total}): {aid}")

            if aid in installed_ids:
                info(f"Skip (already installed): {aid}")
                skipped.append(aid)
                continue

            try:
                info(f"Install request: {aid}", notify=True)
                rpc.install_addon(aid)  # should call InstallAddon builtin internally

                ok, why = _wait_until_installed_by_list(rpc, aid, timeout_s=timeout_per_addon_s)
                if ok:
                    installed.append(aid)
                    installed_ids.add(aid)
                else:
                    err(f"Install failed: {aid} - {why}", notify=True)
                    failed.append({"id": aid, "error": why})

            except Exception as e:
                exc(f"Exception installing {aid}: {e}")
                failed.append({"id": aid, "error": str(e)})

        return installed, skipped, failed

    finally:
        dialog.close()


def run_install(manifest: dict):
    _validate_manifest(manifest)

    repos = manifest.get("repos") or []
    addons = manifest.get("addons") or []

    info(f"run_install: repos={len(repos)} addons={len(addons)}", notify=True)

    report = {
        "repos": {"installed": [], "skipped": [], "failed": []},
        "addons": {"installed": [], "skipped": [], "failed": []},
    }

    # 1) Install repos by EXTRACT
    if repos:
        r_inst, r_skip, r_fail = _install_repos(repos, timeout_per_repo_s=90)
        report["repos"] = {"installed": r_inst, "skipped": r_skip, "failed": r_fail}

        if r_fail:
            warn(f"{len(r_fail)} repo(s) failed to install. Some addons may not resolve.", notify=True)

    # 2) Refresh repos ONCE more
    xbmc.executebuiltin("UpdateAddonRepos")
    _sleep(10000)  # Firestick needs longer

    # 3) Install addons
    a_inst, a_skip, a_fail = _install_addons(addons, timeout_per_addon_s=60)
    report["addons"] = {"installed": a_inst, "skipped": a_skip, "failed": a_fail}

    info(
        f"Install summary: repos ok={len(report['repos']['installed'])} fail={len(report['repos']['failed'])} | "
        f"addons ok={len(report['addons']['installed'])} fail={len(report['addons']['failed'])}",
        notify=True
    )

    return report
