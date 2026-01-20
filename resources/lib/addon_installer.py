import os
import time
import zipfile
import shutil
import xbmc
import xbmcgui
import xbmcvfs
import urllib.request

from resources.lib.jsonrpc import JsonRpc
from resources.lib.log import info, warn, err, exc
from resources.lib.paths import temp, home

# Kodi's official built-in repo - skip it always
BUILTIN_REPOS = {"repository.xbmc.org"}


# -------------------------
# helpers
# -------------------------

def _ensure_dir(path: str):
    if not xbmcvfs.exists(path):
        xbmcvfs.mkdirs(path)


def _safe_rmtree(path: str):
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
    except Exception as e:
        warn(f"Failed to remove folder {path}: {e}")


def _download_to(url: str, dst_path: str):
    """
    Download url -> dst_path (binary). Raises on failure.
    Uses urllib (works on Kodi Python).
    """
    info(f"Downloading: {url} -> {dst_path}", notify=True)
    _ensure_dir(os.path.dirname(dst_path))

    with urllib.request.urlopen(url, timeout=60) as r:
        with open(dst_path, "wb") as f:
            while True:
                chunk = r.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)

    if not os.path.isfile(dst_path) or os.path.getsize(dst_path) < 1024:
        raise RuntimeError(f"Downloaded file looks wrong: {dst_path}")


def _zip_has_expected_top_folder(zip_path: str, expected_folder: str) -> bool:
    """
    Validate that zip contains expected_folder/... as top-level.
    Example: repository.cocoscrapers/addon.xml
    """
    expected_prefix = expected_folder.rstrip("/") + "/"
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            names = z.namelist()
            return any(n.startswith(expected_prefix) for n in names)
    except Exception:
        return False


def install_repo_zip_locally(repo_id: str, zip_path: str, timeout_s: int = 30) -> (bool, str):
    """
    Firestick-safe repo "install":
    - unzip repo zip into special://home/addons/
    - UpdateLocalAddons (so Kodi registers it)
    - EnableAddon(repo_id)
    - wait for folder + optionally installed list
    """
    addons_dir = home("addons")
    dest_dir = os.path.join(addons_dir, repo_id)

    info(f"Installing repo by extract: {repo_id} zip={zip_path}", notify=True)

    if not os.path.isfile(zip_path):
        return False, f"Repo zip missing: {zip_path}"

    # sanity: correct zip layout
    if not _zip_has_expected_top_folder(zip_path, repo_id):
        return False, f"Zip layout invalid (missing top folder '{repo_id}/')"

    # wipe existing repo folder (avoid mixed old/new)
    _safe_rmtree(dest_dir)

    # extract into addons root
    try:
        _ensure_dir(addons_dir)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(addons_dir)
    except Exception as e:
        return False, f"Extract failed: {e}"

    # wait for folder to appear (filesystem)
    start = time.time()
    while True:
        if os.path.isdir(dest_dir):
            break
        if time.time() - start >= timeout_s:
            return False, f"Folder never appeared after extract: {dest_dir}"
        xbmc.sleep(500)

    # tell Kodi to rescan local addons
    xbmc.executebuiltin("UpdateLocalAddons")
    xbmc.sleep(1500)

    # enable it (harmless if already enabled)
    xbmc.executebuiltin(f"EnableAddon({repo_id})")
    xbmc.sleep(1500)

    return True, ""


def _preflight_or_die(rpc: JsonRpc):
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

        xbmc.sleep(1000)


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

    if not isinstance(addons, list):
        raise RuntimeError("Manifest invalid: addons must be a list")
    for a in addons:
        if not isinstance(a, str):
            raise RuntimeError("Manifest invalid: addons must be strings")
        if a.startswith("repository."):
            raise RuntimeError("Manifest invalid: addons list must not contain repository.* IDs")


# -------------------------
# install logic
# -------------------------

def _install_repos(repo_entries, timeout_per_repo_s: int = 45):
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

            # Always skip Kodi built-in repo
            if rid in BUILTIN_REPOS:
                info(f"Skip built-in repo: {rid}")
                skipped.append(rid)
                continue

            if rid in installed_ids:
                info(f"Skip repo (already installed): {rid}")
                skipped.append(rid)
                continue

            try:
                # If we only have URL, download it to temp
                if not zip_path and zip_url:
                    zip_path = temp(f"profiler_repo_zips/{rid}.zip")
                    info(f"Repo zip_url fallback for {rid}: {zip_url}")
                    _download_to(zip_url, zip_path)

                if not zip_path:
                    err(f"Repo has no zip_path or zip_url: {rid}", notify=True)
                    failed.append({"id": rid, "error": "Missing zip_path and zip_url"})
                    continue

                ok, why = install_repo_zip_locally(rid, zip_path, timeout_s=timeout_per_repo_s)
                if not ok:
                    err(f"Repo install failed: {rid} - {why}", notify=True)
                    failed.append({"id": rid, "error": why})
                    continue

                # refresh repos list after each successful repo install (helps Firestick)
                xbmc.executebuiltin("UpdateLocalAddons")
                xbmc.sleep(1500)

                installed.append(rid)
                installed_ids.add(rid)

            except Exception as e:
                exc(f"Exception installing repo {rid}: {e}")
                failed.append({"id": rid, "error": str(e)})

        return installed, skipped, failed

    finally:
        dialog.close()


def _install_addons(addon_ids, timeout_per_addon_s: int = 45):
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
                rpc.install_addon(aid)

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

    # 1) Install repos using EXTRACT method
    if repos:
        r_inst, r_skip, r_fail = _install_repos(repos, timeout_per_repo_s=45)
        report["repos"] = {"installed": r_inst, "skipped": r_skip, "failed": r_fail}

        if r_fail:
            warn(f"{len(r_fail)} repo(s) failed to install. Some addons may not resolve.", notify=True)

    # 2) Force refresh after repos are installed
    rpc = JsonRpc()
    xbmc.executebuiltin("UpdateLocalAddons")
    xbmc.sleep(2000)

    rpc.update_addon_repos()
    xbmc.sleep(8000)  # Firestick needs longer

    # 3) Install addons
    a_inst, a_skip, a_fail = _install_addons(addons, timeout_per_addon_s=45)
    report["addons"] = {"installed": a_inst, "skipped": a_skip, "failed": a_fail}

    info(
        f"Install summary: repos ok={len(report['repos']['installed'])} fail={len(report['repos']['failed'])} | "
        f"addons ok={len(report['addons']['installed'])} fail={len(report['addons']['failed'])}",
        notify=True
    )

    return report
