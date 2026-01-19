import os
import time
import xbmcvfs

def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def copy_file(src: str, dst: str, retries: int = 5, delay: float = 0.2) -> None:
    ensure_dir(os.path.dirname(dst))

    last_err = None
    for _ in range(retries):
        try:
            with open(src, "rb") as fsrc:
                data = fsrc.read()
            with open(dst, "wb") as fdst:
                fdst.write(data)
            return
        except Exception as e:
            last_err = e
            time.sleep(delay)

    raise IOError(f"Failed to copy {src} -> {dst}. Last error: {last_err}")

def walk_dir(root: str):
    # Generator of (dirpath, files)
    dirs, files = xbmcvfs.listdir(root)
    yield root, files
    for d in dirs:
        sub = root.rstrip("/") + "/" + d
        yield from walk_dir(sub)
