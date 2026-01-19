import os
import zipfile
import xbmcvfs

def zip_from_dir(staging_dir: str, out_zip: str) -> None:
    # staging_dir/out_zip are real filesystem paths from translatePath
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(staging_dir):
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, staging_dir)
                z.write(full, rel)

def unzip_to_dir(zip_path: str, staging_dir: str) -> None:
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(staging_dir)
