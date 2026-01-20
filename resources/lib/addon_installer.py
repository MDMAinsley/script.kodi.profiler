import time
import xbmc
import xbmcgui

from resources.lib.jsonrpc import JsonRpc
from resources.lib.log import info, warn, err, exc


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


def _install_list(title: str, items, timeout_per_item_s: int = 45):
    """
    Generic installer for repos OR addons.
    """
    rpc = JsonRpc()
    _preflight_or_die(rpc)

    installed_ids = rpc.get_installed_ids()

    installed = []
    skipped = []
    failed = []

    dialog = xbmcgui.DialogProgress()
    dialog.create("Profiler", title)

    try:
        total = len(items) or 1

        for i, item_id in enumerate(items, start=1):
            if dialog.iscanceled():
                warn("User cancelled install phase", notify=True)
                failed.append({"id": item_id, "error": "User cancelled"})
                break

            pct = int((i / total) * 100)
            dialog.update(pct, f"{title} ({i}/{total}): {item_id}")

            if item_id in installed_ids:
                info(f"Skip (already installed): {item_id}")
                skipped.append(item_id)
                continue

            try:
                info(f"Install request: {item_id}", notify=True)
                rpc.install_addon(item_id)

                ok, why = _wait_until_installed_by_list(rpc, item_id, timeout_s=timeout_per_item_s)
                if ok:
                    installed.append(item_id)
                    installed_ids.add(item_id)
                else:
                    err(f"Install failed: {item_id} - {why}", notify=True)
                    failed.append({"id": item_id, "error": why})

            except Exception as e:
                exc(f"Exception installing {item_id}: {e}")
                failed.append({"id": item_id, "error": str(e)})

        return installed, skipped, failed

    finally:
        dialog.close()


def _split_repos_and_addons(manifest: dict):
    """
    Support your current manifest format.
    - If manifest["repos"] is empty, auto-detect repos from addons list (repository.*).
    - Also removes repos from addons list so we don’t install them twice.
    """
    repos = (manifest.get("repos") or [])
    addons = (manifest.get("addons") or [])

    # auto detect repos if repos list not populated
    if not repos:
        repos = [a for a in addons if a.startswith("repository.")]
    # remove repos from addon list
    addons = [a for a in addons if not a.startswith("repository.")]

    return repos, addons


def run_install(manifest: dict):
    repos, addons = _split_repos_and_addons(manifest)

    info(f"run_install: repos={len(repos)} addons={len(addons)}", notify=True)

    report = {
        "repos": {"installed": [], "skipped": [], "failed": []},
        "addons": {"installed": [], "skipped": [], "failed": []},
    }

    # 1) Install repos first (so third-party addons can resolve)
    if repos:
        r_inst, r_skip, r_fail = _install_list("Installing repos", repos, timeout_per_item_s=45)
        report["repos"] = {"installed": r_inst, "skipped": r_skip, "failed": r_fail}

        # If repos failed badly, warn but continue (some addons may still work)
        if r_fail:
            warn(f"{len(r_fail)} repo(s) failed to install. Some addons may not resolve.", notify=True)

    # 2) Force refresh after repos are installed
    rpc = JsonRpc()
    rpc.update_addon_repos()
    xbmc.sleep(5000)  # Firestick needs longer

    # 3) Install addons
    a_inst, a_skip, a_fail = _install_list("Installing add-ons", addons, timeout_per_item_s=180)
    report["addons"] = {"installed": a_inst, "skipped": a_skip, "failed": a_fail}

    info(
        f"Install summary: repos ok={len(report['repos']['installed'])} fail={len(report['repos']['failed'])} | "
        f"addons ok={len(report['addons']['installed'])} fail={len(report['addons']['failed'])}",
        notify=True
    )

    return report
