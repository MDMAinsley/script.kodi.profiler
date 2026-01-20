from resources.lib.jsonrpc import JsonRpc

def build_manifest() -> dict:
    rpc = JsonRpc()

    skin = rpc.call("Settings.GetSettingValue", {"setting": "lookandfeel.skin"}).get("value", "")

    result = rpc.call("Addons.GetAddons", {"installed": True})
    addons = result.get("addons", []) or []

    addon_ids = sorted({a.get("addonid") for a in addons if a.get("addonid")})

    # Repos are just addons with id starting with repository.
    repo_ids = sorted([a for a in addon_ids if a.startswith("repository.")])
    addon_ids = sorted([a for a in addon_ids if not a.startswith("repository.")])

    return {
        "kodi_major": 21,
        "active_skin": skin,
        "repos": [{"id": rid, "zip_in_backup": "", "zip_url": ""} for rid in repo_ids],
        "addons": addon_ids,
    }
