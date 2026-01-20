from resources.lib.jsonrpc import JsonRpc


def build_manifest() -> dict:
    rpc = JsonRpc()

    # Active skin (useful to restore later)
    skin = rpc.call("Settings.GetSettingValue", {"setting": "lookandfeel.skin"}).get("value", "")

    # Installed addon IDs
    result = rpc.call("Addons.GetAddons", {"installed": True})
    addons = result.get("addons", []) or []
    addon_ids = sorted({a.get("addonid") for a in addons if a.get("addonid")})

    # Separate repos vs addons
    repo_ids = sorted([
        a for a in addon_ids
        if a.startswith("repository.")
        and not a.startswith("repository.xbmc")
    ])
    addon_ids = sorted([a for a in addon_ids if not a.startswith("repository.")])

    # Kodi major version (best effort; safe default)
    try:
        kodi_version = rpc.call("Application.GetProperties", {"properties": ["version"]}).get("version", {})
        major = int(kodi_version.get("major", 0)) or 21
    except Exception:
        major = 21

    return {
        "kodi_major": major,
        "active_skin": skin,
        "repos": [
            {
                "id": rid,
                "zip_in_backup": "",  # e.g. "repos/repository.kodinerds-3.1.2.zip"
                "zip_url": "",        # optional fallback (C2)
                "zip_path": "",       # runtime-only: absolute path after extraction
            }
            for rid in repo_ids
        ],
        "addons": addon_ids,
    }
