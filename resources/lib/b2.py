import base64
import hashlib
import json
from typing import Optional, Dict, Any
import urllib.request
import urllib.parse

from typing import Optional, Dict, Any

class B2Client:
    def __init__(self, key_id: str, app_key: str):
        self.key_id = key_id
        self.app_key = app_key
        self.api_url = None
        self.download_url = None
        self.account_auth_token = None
        self.account_id = None

    def _req_json(self, url: str, headers: Dict[str, str], body: Optional[Dict[str, Any]]):
        try:
            data = None
            if body is not None:
                data = json.dumps(body).encode("utf-8")
                headers = {**headers, "Content-Type": "application/json"}
            req = urllib.request.Request(
                url,
                data=data,
                headers=headers,
                method="POST" if body is not None else "GET",
            )
            with urllib.request.urlopen(req) as resp:
                raw = resp.read()
                return json.loads(raw.decode("utf-8")) if raw else {}
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"B2 HTTP {e.code} on {url}: {body}")

    def authorize(self):
        # b2_authorize_account :contentReference[oaicite:19]{index=19}
        creds = f"{self.key_id}:{self.app_key}".encode("utf-8")
        b64 = base64.b64encode(creds).decode("ascii")
        url = "https://api.backblazeb2.com/b2api/v2/b2_authorize_account"
        # Note: docs also describe newer API structures; v2 authorize endpoint remains valid for Native API suites. :contentReference[oaicite:20]{index=20}
        out = self._req_json(url, {"Authorization": f"Basic {b64}"}, body=None)
        self.api_url = out["apiUrl"]
        self.download_url = out["downloadUrl"]
        self.account_auth_token = out["authorizationToken"]
        self.account_id = out["accountId"]
        return out

    def list_buckets(self):
        # b2_list_buckets :contentReference[oaicite:21]{index=21}
        url = f"{self.api_url}/b2api/v2/b2_list_buckets"
        return self._req_json(url, {"Authorization": self.account_auth_token}, {"accountId": self.account_id})

    def get_bucket_id(self, bucket_name: str) -> str:
        # list buckets and match name
        url = f"{self.api_url}/b2api/v2/b2_list_buckets"
        out = self._req_json(url, {"Authorization": self.account_auth_token}, {"accountId": self.account_id})
        for b in out.get("buckets", []):
            if b.get("bucketName") == bucket_name:
                return b["bucketId"]
        raise RuntimeError(f"Bucket not found: {bucket_name}")

    def list_file_names(self, bucket_id: str, prefix: str = ""):
        # b2_list_file_names :contentReference[oaicite:22]{index=22}
        url = f"{self.api_url}/b2api/v2/b2_list_file_names"
        body = {"bucketId": bucket_id, "maxFileCount": 1000}
        if prefix:
            body["prefix"] = prefix
        return self._req_json(url, {"Authorization": self.account_auth_token}, body)

    def get_upload_url(self, bucket_id: str):
        # b2_get_upload_url :contentReference[oaicite:23]{index=23}
        url = f"{self.api_url}/b2api/v2/b2_get_upload_url"
        return self._req_json(url, {"Authorization": self.account_auth_token}, {"bucketId": bucket_id})

    def upload_file(self, upload_url: str, upload_auth_token: str, file_name: str, data_bytes: bytes, content_type="application/zip"):
        try:
            # b2_upload_file :contentReference[oaicite:24]{index=24}
            sha1 = hashlib.sha1(data_bytes).hexdigest()
            headers = {
                "Authorization": upload_auth_token,
                "X-Bz-File-Name": urllib.parse.quote(file_name, safe="/"),
                "Content-Type": content_type,
                "X-Bz-Content-Sha1": sha1,
                "Content-Length": str(len(data_bytes)),
            }
            req = urllib.request.Request(upload_url, data=data_bytes, headers=headers, method="POST")
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"B2 HTTP {e.code} on {url}: {body}")

    def download_by_name(self, bucket_name: str, file_name: str) -> bytes:
        try:
            # b2_download_file_by_name :contentReference[oaicite:25]{index=25}
            url = f"{self.download_url}/file/{bucket_name}/{file_name}"
            req = urllib.request.Request(url, headers={"Authorization": self.account_auth_token}, method="GET")
            with urllib.request.urlopen(req) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"B2 HTTP {e.code} on {url}: {body}")
