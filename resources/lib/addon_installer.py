import time
import xbmc
import xbmcgui

from resources.lib.jsonrpc import JsonRpc
from resources.lib.log import info, warn, err, exc, log


def _get_installed_ids(rpc: JsonRpc):
    res = rpc.call("Addons.GetAddons", {"installed": True})
    addons = res.get("addons", []) or []
    return {a.get("addonid") for a in addons if a.get("addonid")}


def _wait_until_installed(rpc: JsonRpc, addon_id: str, timeout_s: int = 180):
    """
    Poll until addon shows up as installed (GetAddonDetails works).
    Logs progress every few seconds.
    """
    start = time.time()
    last_log = 0

    while True:
        elapsed = int(time.time() - start)
        if elapsed >= timeout_s:
            return False, f"Timed out after {timeout_s}s"

        # log heartbeat every 5s so we can see it's alive
        if elapsed - last_log >= 5:
            info(f"Waiting for install: {addon_id} ({elapsed}s/{timeout_s}s)")
            last_log = elapsed

        try:
            if rpc.is_addon_installed(addon_id):
                details = rpc.get_addon_details(addon_id).get("addon", {})
                ver = details.get("version", "?")
                enabled = details.get("enabled", None)
                info(f"Installed: {addon_id} version={ver} enabled={enabled}")
                return True, ""
        except Exception as e:
            # don't hide it — log once in a while
            warn(f"GetAddonDetails failed while waiting: {addon_id} ({e})")

        xbmc.sleep(1000)


def _preflight_or_die(rpc: JsonRpc):
    """
    If Kodi’s addon system is broken, fail loudly.
    """
    try:
        rpc.call("Addons.GetAddons", {"installed": True})
        info("Addon system preflight OK")
    except Exception:
        exc("Addon system preflight failed (JSON-RPC Addons.GetAddons). Addon DB may be broken.")
        raise


def install_addons(addon_ids, timeout_per_addon_s=180):
    rpc = JsonRpc()
    _preflight_or_die(rpc)

    installed_ids = _get_installed_ids(rpc)

    installed = []
    skipped = []
    failed = []

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
            dialog.update(pct, f"{i}/{total}", f"Installing: {aid}")

            if aid in installed_ids:
                info(f"Skip (already installed): {aid}")
                skipped.append(aid)
                continue

            try:
                info(f"Install request: {aid}", notify=True)
                rpc.install_addon(aid)

                ok, why = _wait_until_installed(rpc, aid, timeout_s=timeout_per_addon_s)
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
    """
    manifest = {"repos": [...], "addons": [...]}
    """
    repos = manifest.get("repos", []) or []
    addons = manifest.get("addons", []) or []

    info(f"run_install: repos={len(repos)} addons={len(addons)}", notify=True)

    # If you later add repo installs back in, we’ll add the same monitoring.
    if repos:
        warn("Repo install list present but not implemented in monitored mode yet. Skipping repos.")
        # You can implement repo installs similarly to install_addons()

    # Force a repo refresh before addon installs
    info("UpdateAddonRepos builtin")
    xbmc.executebuiltin("UpdateAddonRepos")
    xbmc.sleep(3000)

    addon_installed, addon_skipped, addon_failed = install_addons(addons)

    return {
        "repos": {"installed": [], "skipped": repos, "failed": []},
        "addons": {"installed": addon_installed, "skipped": addon_skipped, "failed": addon_failed},
    }
