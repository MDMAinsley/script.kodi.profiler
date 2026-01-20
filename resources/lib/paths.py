import xbmcvfs

def tr(path: str) -> str:
    return xbmcvfs.translatePath(path)

def home(path: str = "") -> str:
    if path and not path.startswith("/"):
        path = "/" + path
    return tr("special://home" + path)

def profile(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return tr("special://profile" + path)

def temp(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return tr("special://temp" + path)
