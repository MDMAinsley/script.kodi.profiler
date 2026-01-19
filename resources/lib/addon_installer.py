import xbmc
from resources.lib.jsonrpc import JsonRpc


def _wait_until_installed(rpc, addon_id, timeout_ms=60000):
    waited = 0
    step = 500

    while waited < timeout_ms:
        try:
            res = rpc.call("Addons.GetAddonDetails", {"addonid": addon_id, "properties": ["enabled"]})
            if "addon" in res:
                return True
        except Exception:
            pass

        xbmc.sleep(step)
        waited += step

    return False

def _get_installed_ids(rpc: JsonRpc):
    """
    Returns a set of addonids currently installed on this Kodi instance.
    One JSON-RPC call (fast).
    """
    res = rpc.call("Addons.GetAddons", {"installed": True})
    addons = res.get("addons", []) or []
    return {a.get("addonid") for a in addons if a.get("addonid")}


def install_repositories(repo_ids, settle_ms=5000):
    """
    Installs repository add-ons first.
    Returns (installed, skipped, failed)
    """
    rpc = JsonRpc()
    installed_ids = _get_installed_ids(rpc)

    installed = []
    skipped = []
    failed = []

    for rid in repo_ids:
        if rid in installed_ids:
            skipped.append(rid)
            continue

        try:
            xbmc.log(f"[Profiler] Installing repo {rid}", xbmc.LOGINFO)
            rpc.install_addon(rid)
            installed.append(rid)
        except Exception as e:
            failed.append({"id": rid, "error": str(e)})

    # give Kodi time to fetch repo metadata before installing dependent addons
    if settle_ms and (installed or skipped):
        xbmc.sleep(settle_ms)

    return installed, skipped, failed

def install_addons(addon_ids):
    """
    Installs non-repo add-ons.
    Returns (installed, skipped, failed)
    """
    rpc = JsonRpc()
    installed_ids = _get_installed_ids(rpc)

    installed = []
    skipped = []
    failed = []
    requested = []

    # Request installs
    for aid in addon_ids:
        if aid in installed_ids:
            skipped.append(aid)
            continue

        try:
            xbmc.log(f"[Profiler] Installing addon {aid}", xbmc.LOGINFO)
            rpc.install_addon(aid)          # may show confirm prompt; your JsonRpc now waits for it
            requested.append(aid)
        except Exception as e:
            failed.append({"id": aid, "error": str(e)})

    if not requested:
        return installed, skipped, failed

    # Give Kodi a moment to start background install jobs
    xbmc.sleep(1500)

    # Re-check installed list once
    installed_after = _get_installed_ids(rpc)

    # Resolve requested -> installed/failed (iterate over a copy)
    for aid in list(requested):
        if aid in installed_after:
            installed.append(aid)
            continue

        # Poll for completion
        if _wait_until_installed(rpc, aid, timeout_ms=60000):
            installed.append(aid)
        else:
            failed.append({"id": aid, "error": "Install requested but not installed after waiting"})

    return installed, skipped, failed

def run_install(manifest: dict):
    """
    Main entry point to install repos then addons using your manifest format.
    manifest = {"repos": [...], "addons": [...]}
    Returns a report dict you can show to the user.
    """
    repos = manifest.get("repos", []) or []
    addons = manifest.get("addons", []) or []

    repo_installed, repo_skipped, repo_failed = install_repositories(repos)
    
    # After repo install (even if none), give Kodi a moment
    xbmc.executebuiltin("UpdateAddonRepos")
    xbmc.sleep(5000)


    addon_installed, addon_skipped, addon_failed = install_addons(addons)

    return {
        "repos": {
            "installed": repo_installed,
            "skipped": repo_skipped,
            "failed": repo_failed,
        },
        "addons": {
            "installed": addon_installed,
            "skipped": addon_skipped,
            "failed": addon_failed         
        },
    }
