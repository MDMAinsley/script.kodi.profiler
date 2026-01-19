from resources.lib.jsonrpc import JsonRpc

def build_manifest() -> dict:
    rpc = JsonRpc()
    
    skin = rpc.call("Settings.GetSettingValue", {"setting": "lookandfeel.skin"}).get("value", "")

    result = rpc.call("Addons.GetAddons", {
        "installed": True,
        "properties": ["name", "version", "enabled"]  # removed "type"
    })

    addons = result.get("addons", []) or []

    repo_ids = []
    addon_ids = []

    for a in addons:
        addonid = a.get("addonid")
        if not addonid:
            continue

        # Fetch details to get the type (repo vs normal addon)
        try:
            details = rpc.call("Addons.GetAddonDetails", {
                "addonid": addonid,
                "properties": ["type"]
            })
            atype = (details.get("addon", {}) or {}).get("type", "")
        except Exception:
            atype = ""

        if atype == "xbmc.addon.repository":
            repo_ids.append(addonid)
        else:
            addon_ids.append(addonid)

    return {
        "kodi_major": 21,
        "active_skin": skin,
        "repos": sorted(set(repo_ids)),
        "addons": sorted(set(addon_ids)),
    }
