import json
import time
import xbmc
from typing import Optional, Dict, Any

try:
    from .uiwait import wait_for_modal_to_close
    from .log import info, warn, err, exc, log
except Exception:
    from uiwait import wait_for_modal_to_close
    from log import info, warn, err, exc, log


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
            # include method and the full error object
            err(f"JSON-RPC error for {method} ({ms}ms): {data['error']}")
            raise RuntimeError(f"JSON-RPC error {data['error']}")

        # useful to see long/slow calls when debugging firestick
        if ms > 750:
            warn(f"JSON-RPC slow call {method}: {ms}ms")

        return data.get("result", {})

    def introspect(self) -> Dict[str, Any]:
        info("JSON-RPC introspect")
        return self.call("JSONRPC.Introspect")

    def set_setting(self, setting: str, value: Any) -> Dict[str, Any]:
        info(f"Setting {setting} -> {value}")
        return self.call("Settings.SetSettingValue", {"setting": setting, "value": value})

    def get_setting(self, setting: str):
        info(f"Get setting {setting}")
        return self.call("Settings.GetSettingValue", {"setting": setting})

    def quit_app(self) -> Dict[str, Any]:
        info("Application.Quit requested")
        return self.call("Application.Quit")

    def install_addon(self, addon_id: str) -> bool:
        """
        Request install. This does NOT guarantee completion.
        We'll monitor completion in addon_installer.py.
        """
        info(f"Install request: {addon_id}")
        try:
            # Kodi JSON-RPC install method
            self.call("Addons.Install", {"addonid": addon_id})
            return True
        except Exception as e:
            # Fall back to builtin if method missing
            s = str(e)
            if "Method not found" in s or "'code': -32601" in s:
                warn(f"Addons.Install not available, using builtin InstallAddon({addon_id})")
                xbmc.executebuiltin(f"InstallAddon({addon_id})")
                wait_for_modal_to_close(timeout_ms=60000)
                return True
            raise

    def is_addon_installed(self, addon_id: str) -> bool:
        try:
            res = self.call("Addons.GetAddonDetails", {"addonid": addon_id, "properties": ["enabled", "version"]})
            return "addon" in res
        except Exception:
            return False

    def get_addon_details(self, addon_id: str) -> Dict[str, Any]:
        return self.call("Addons.GetAddonDetails", {"addonid": addon_id, "properties": ["enabled", "version", "name"]})

    def get_installed_addons(self):
        return self.call("Addons.GetAddons", {"installed": True, "properties": ["addonid", "type"]}).get("addons", [])
