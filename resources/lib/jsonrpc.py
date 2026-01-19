import json
import xbmc
from typing import Optional, Dict, Any
try:
    # Works when imported as resources.lib.jsonrpc (default.py path)
    from .uiwait import wait_for_modal_to_close
except Exception:
    # Works when service.py injects resources/lib into sys.path
    from uiwait import wait_for_modal_to_close


class JsonRpc:
    def __init__(self):
        self._id = 1

    def call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method}
        self._id += 1
        if params is not None:
            payload["params"] = params
        raw = xbmc.executeJSONRPC(json.dumps(payload))
        data = json.loads(raw) if raw else {}
        if "error" in data:
            raise RuntimeError(f"JSON-RPC error {data['error']}")
        return data.get("result", {})

    def introspect(self) -> Dict[str, Any]:
        return self.call("JSONRPC.Introspect")
        
    def set_setting(self, setting: str, value: Any) -> Dict[str, Any]:
        return self.call("Settings.SetSettingValue", {
            "setting": setting,
            "value": value
        })
        
    def get_setting(self, setting: str):
        return self.call("Settings.GetSettingValue", {"setting": setting})
        
    def quit_app(self) -> Dict[str, Any]:
        return self.call("Application.Quit")
        
    def install_addon(self, addon_id: str) -> bool:
        # Try JSON-RPC first (if available)
        try:
            self.call("Addons.Install", {"addonid": addon_id})
            return True
        except Exception as e:
            # If method not found, fall back to builtin
            if "Method not found" in str(e) or "'code': -32601" in str(e):
                xbmc.executebuiltin(f'InstallAddon({addon_id})')
                
                # Wait for user to answer the install confirmation dialog
                wait_for_modal_to_close(timeout_ms=60000)
                return True
            raise

    def is_addon_installed(self, addon_id: str) -> bool:
        res = self.call(
            "Addons.GetAddonDetails",
            {"addonid": addon_id, "properties": ["enabled"]}
        )
        return "addon" in res

    def get_installed_addons(self):
        return self.call(
            "Addons.GetAddons",
            {"installed": True, "properties": ["addonid", "type"]}
        ).get("addons", [])
