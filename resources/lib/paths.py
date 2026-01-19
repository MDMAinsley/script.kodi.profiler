import xbmcvfs

def tr(path: str) -> str:
    # Kodi v19+ replacement for xbmc.translatePath
    return xbmcvfs.translatePath(path)  # :contentReference[oaicite:7]{index=7}

def profile(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return tr("special://profile" + path)

def temp(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return tr("special://temp" + path)
