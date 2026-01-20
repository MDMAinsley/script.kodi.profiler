import json
import time
import xbmc
from typing import Optional, Dict, Any, List

try:
    from .uiwait import wait_for_modal_to_close
    from .log import info, warn, err
except Exception:
    from uiwait import wait_for_modal_to_close
    from log import info, warn, err


class JsonRpc:
    def __init__(self):
        self._id = 1

    def call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method}
        self._id += 1
        if params is not None:
            payload["params"] = params

        t0 = time.time()
        raw = xbmc.executeJSONRPC(json.dumps(payload))
        ms = int((time.time() - t0) * 1000)

        if not raw:
            err(f"JSON-RPC returned empty response for {method} ({ms}ms)")
            raise RuntimeError(f"JSON-RPC empty response: {method}")

        try:
            data = json.loads(raw)
        except Exception:
            err(f"JSON-RPC invalid JSON for {method} ({ms}ms): {raw[:200]}")
            raise

        if "error" in data:
            err(f"JSON-RPC error for {method} ({ms}ms): {data['error']}")
            raise RuntimeError(f"JSON-RPC error {data['error']}")

        return data.get("result", {})

    # --- Add-on listing (Firestick-safe) ---

    def get_installed_addons(self) -> List[Dict[str, Any]]:
        res = self.call("Addons.GetAddons", {"installed": True})
        return res.get("addons", []) or []

    def get_installed_ids(self) -> set:
        return {a.get("addonid") for a in self.get_installed_addons() if a.get("addonid")}

    def update_addon_repos(self):
        info("UpdateAddonRepos builtin")
        xbmc.executebuiltin("UpdateAddonRepos")

    # --- Settings ---

    def set_setting(self, setting: str, value):
        info(f"Setting {setting} -> {value}")
        return self.call("Settings.SetSettingValue", {"setting": setting, "value": value})

    def get_setting(self, setting: str):
        info(f"Get setting {setting}")
        return self.call("Settings.GetSettingValue", {"setting": setting})

    # --- Install request (fallback to builtin) ---

    def install_addon(self, addon_id: str) -> bool:
        """
        Request install by ID (not zip). Completion is monitored by addon_installer.py.
        Firestick often lacks Addons.Install JSON-RPC, so fallback to builtin.
        """
        info(f"Install request: {addon_id}")
        try:
            self.call("Addons.Install", {"addonid": addon_id})
            return True
        except Exception as e:
            s = str(e)
            if "Method not found" in s or "'code': -32601" in s:
                warn(f"Addons.Install not available, using builtin InstallAddon({addon_id})")
                xbmc.executebuiltin(f"InstallAddon({addon_id})")
                wait_for_modal_to_close(timeout_ms=60000)
                return True
            raise

    def install_zip(self, zip_path: str):
        """
        Install a LOCAL zip file (repo zip) reliably on Firestick.
        Use InstallAddon(<zip_path>) — works across versions.
        """
        info(f"Install zip: {zip_path}")
        # InstallAddon accepts a local zip path
        xbmc.executebuiltin(f'InstallAddon("{zip_path}")')
        wait_for_modal_to_close(timeout_ms=60000)
