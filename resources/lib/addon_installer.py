import os
import time
import xbmc
import xbmcgui
import xbmcvfs
import urllib.request

from resources.lib.jsonrpc import JsonRpc
from resources.lib.log import info, warn, err, exc
from resources.lib.paths import temp


def _ensure_dir(path: str):
    if not xbmcvfs.exists(path):
        xbmcvfs.mkdirs(path)


def _download_to(url: str, dst_path: str):
    """
    Download url -> dst_path (binary). Raises on failure.
    Uses urllib (works on Kodi Python).
    """
    info(f"Downloading: {url} -> {dst_path}", notify=True)
    _ensure_dir(os.path.dirname(dst_path))

    # urllib wants a normal filesystem path; dst_path already is translated via temp()
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
    try:
        rpc.get_installed_addons()
        info("Addon system preflight OK")
    except Exception:
        exc("Addon system preflight failed (Addons.GetAddons). Addon DB may be broken.")
        raise


def _wait_until_installed_by_list(rpc: JsonRpc, addon_id: str, timeout_s: int = 180):
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


def _install_repos(repo_entries, timeout_per_repo_s: int = 180):
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

            if rid in installed_ids:
                info(f"Skip repo (already installed): {rid}")
                skipped.append(rid)
                continue

            try:
                # C1: zip included in backup (resolved to zip_path during restore)
                if zip_path:
                    info(f"Installing repo from local zip: {rid} -> {zip_path}", notify=True)
                    rpc.install_zip(zip_path)

                # C2: zip_url fallback
                elif zip_url:
                    local_zip = temp(f"profiler_repo_zips/{rid}.zip")
                    info(f"Repo zip_url fallback for {rid}: {zip_url}")
                    _download_to(zip_url, local_zip)
                    rpc.install_zip(local_zip)

                else:
                    # Dicts-only policy: no id-only installs
                    err(f"Repo has no zip_path or zip_url: {rid}", notify=True)
                    failed.append({"id": rid, "error": "Missing zip_path and zip_url"})
                    continue

                ok, why = _wait_until_installed_by_list(rpc, rid, timeout_s=timeout_per_repo_s)
                if ok:
                    installed.append(rid)
                    installed_ids.add(rid)
                else:
                    err(f"Repo install failed: {rid} - {why}", notify=True)
                    failed.append({"id": rid, "error": why})

            except Exception as e:
                exc(f"Exception installing repo {rid}: {e}")
                failed.append({"id": rid, "error": str(e)})

        return installed, skipped, failed

    finally:
        dialog.close()


def _install_addons(addon_ids, timeout_per_addon_s: int = 180):
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

    # 1) Install repos from zips (C1) or zip_url (C2)
    if repos:
        r_inst, r_skip, r_fail = _install_repos(repos, timeout_per_repo_s=180)
        report["repos"] = {"installed": r_inst, "skipped": r_skip, "failed": r_fail}

        if r_fail:
            warn(f"{len(r_fail)} repo(s) failed to install. Some addons may not resolve.", notify=True)

    # 2) Force refresh after repos are installed
    rpc = JsonRpc()
    rpc.update_addon_repos()
    xbmc.sleep(8000)  # Firestick needs longer

    # 3) Install addons
    a_inst, a_skip, a_fail = _install_addons(addons, timeout_per_addon_s=180)
    report["addons"] = {"installed": a_inst, "skipped": a_skip, "failed": a_fail}

    info(
        f"Install summary: repos ok={len(report['repos']['installed'])} fail={len(report['repos']['failed'])} | "
        f"addons ok={len(report['addons']['installed'])} fail={len(report['addons']['failed'])}",
        notify=True
    )

    return report
