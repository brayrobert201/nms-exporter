"""Versioned save backup to an S3 bucket (Garage). Standard library only.

Every save the game writes is uploaded with its manifest, under a key that
carries the file's own mtime, so each upload is idempotent and a re-run after a
restart rewrites the same objects rather than duplicating them:

    <st_dir>/<stem>/<UTC mtime>/<stem>.hg      e.g. st_7656.../save3/20261022T091203Z/save3.hg
    <st_dir>/<stem>/<UTC mtime>/mf_<stem>.hg

The newest save of any slot is also kept at a fixed path, overwritten in place:

    current/save.hg  current/mf_save.hg  current/info.json

Garage has no S3 object versioning, so a version is simply another key.
Retention (prune): everything for KEEP_ALL days, the newest per hour for
KEEP_HOURLY days, the newest per day after that.

Configuration comes from the environment (the systemd unit reads
/etc/nms-exporter/s3.env): NMS_S3_ACCESS_KEY and NMS_S3_SECRET_KEY are
required; NMS_S3_ENDPOINT (default http://127.0.0.1:3900, this host's Garage
node), NMS_S3_BUCKET (nms-saves) and NMS_S3_REGION (garage) are optional.
Without keys the backup is disabled and says so; nothing here ever raises.
"""
from __future__ import annotations

import datetime as dt
import glob
import hashlib
import hmac
import http.client
import json
import os
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET

KEEP_ALL_DAYS = 7
KEEP_HOURLY_DAYS = 30
PRUNE_EVERY_S = 6 * 3600
SETTLE_S = 2.0          # the game may still be writing a file younger than this


# --- SigV4 ---------------------------------------------------------------------
def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _quote(s: str, safe: str = "-_.~") -> str:
    return urllib.parse.quote(s, safe=safe)


def sign(method: str, host: str, path: str, query: dict, headers: dict, payload_hash: str,
         access: str, secret: str, region: str, amz_date: str, service: str = "s3") -> str:
    """The Authorization header value for an AWS SigV4 request. `path` is the
    already-encoded URI path; `headers` must include host and every x-amz-*."""
    date = amz_date[:8]
    canon_q = "&".join(f"{_quote(k)}={_quote(str(v))}" for k, v in sorted(query.items()))
    hdrs = {k.lower(): " ".join(str(v).split()) for k, v in headers.items()}
    signed = ";".join(sorted(hdrs))
    canon_h = "".join(f"{k}:{hdrs[k]}\n" for k in sorted(hdrs))
    creq = "\n".join([method, path, canon_q, canon_h, signed, payload_hash])
    scope = f"{date}/{region}/{service}/aws4_request"
    sts = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(creq.encode()).hexdigest()])
    k = _hmac(_hmac(_hmac(_hmac(("AWS4" + secret).encode(), date), region), service), "aws4_request")
    sig = hmac.new(k, sts.encode(), hashlib.sha256).hexdigest()
    return f"AWS4-HMAC-SHA256 Credential={access}/{scope}, SignedHeaders={signed}, Signature={sig}"


class S3:
    """Path-style S3 client: just PUT, DELETE and ListObjectsV2."""

    def __init__(self, endpoint: str, bucket: str, access: str, secret: str, region: str = "garage"):
        u = urllib.parse.urlsplit(endpoint)
        self.https = u.scheme == "https"
        self.host = u.netloc
        self.bucket, self.access, self.secret, self.region = bucket, access, secret, region

    def _request(self, method: str, key: str = "", query: dict | None = None, body: bytes = b"",
                 timeout: float = 60) -> tuple[int, bytes]:
        query = query or {}
        path = "/" + _quote(self.bucket) + ("/" + "/".join(_quote(p) for p in key.split("/")) if key else "")
        amz_date = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        ph = hashlib.sha256(body).hexdigest()
        headers = {"host": self.host, "x-amz-date": amz_date, "x-amz-content-sha256": ph}
        headers["authorization"] = sign(method, self.host, path, query, dict(headers), ph,
                                        self.access, self.secret, self.region, amz_date)
        if body:
            headers["content-length"] = str(len(body))
        url = path + ("?" + "&".join(f"{_quote(k)}={_quote(str(v))}" for k, v in sorted(query.items())) if query else "")
        conn = (http.client.HTTPSConnection if self.https else http.client.HTTPConnection)(self.host, timeout=timeout)
        try:
            conn.request(method, url, body=body or None, headers=headers)
            r = conn.getresponse()
            return r.status, r.read()
        finally:
            conn.close()

    def put(self, key: str, body: bytes):
        st, data = self._request("PUT", key, body=body)
        if st != 200:
            raise RuntimeError(f"PUT {key}: HTTP {st} {data[:200]!r}")

    def delete(self, key: str):
        st, data = self._request("DELETE", key)
        if st not in (200, 204):
            raise RuntimeError(f"DELETE {key}: HTTP {st} {data[:200]!r}")

    def list(self, prefix: str = "") -> list[str]:
        keys, token = [], None
        while True:
            q = {"list-type": "2", "prefix": prefix}
            if token:
                q["continuation-token"] = token
            st, data = self._request("GET", query=q)
            if st != 200:
                raise RuntimeError(f"LIST {prefix}: HTTP {st} {data[:200]!r}")
            root = ET.fromstring(data)
            ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
            keys += [c.findtext(f"{ns}Key") for c in root.findall(f"{ns}Contents")]
            if root.findtext(f"{ns}IsTruncated") != "true":
                return keys
            token = root.findtext(f"{ns}NextContinuationToken")


# --- retention -------------------------------------------------------------------
def to_keep(stamps: list[str], now: float) -> set[str]:
    """Which version stamps (YYYYmmddTHHMMSSZ) the retention policy keeps."""
    keep, hourly, daily = set(), {}, {}
    for s in stamps:
        t = dt.datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc).timestamp()
        age_days = (now - t) / 86400
        if age_days <= KEEP_ALL_DAYS:
            keep.add(s)
        elif age_days <= KEEP_HOURLY_DAYS:
            hourly[s[:11]] = max(hourly.get(s[:11], s), s)      # newest within the hour
        else:
            daily[s[:8]] = max(daily.get(s[:8], s), s)          # newest within the day
    return keep | set(hourly.values()) | set(daily.values())


# --- the backup job ----------------------------------------------------------------
class SaveBackup:
    def __init__(self, env=os.environ):
        self.access = env.get("NMS_S3_ACCESS_KEY", "")
        self.secret = env.get("NMS_S3_SECRET_KEY", "")
        self.endpoint = env.get("NMS_S3_ENDPOINT", "http://127.0.0.1:3900")
        self.bucket = env.get("NMS_S3_BUCKET", "nms-saves")
        self.region = env.get("NMS_S3_REGION", "garage")
        self.enabled = bool(self.access and self.secret)
        self.s3 = S3(self.endpoint, self.bucket, self.access, self.secret, self.region) if self.enabled else None
        self._lock = threading.Lock()
        self._running = False
        self._seen: dict = {}          # file -> mtime already uploaded (this process)
        self._current: tuple = ("", 0.0)   # (path, mtime) last written to current/
        self.uploads = self.errors = 0
        self.last_upload = self.last_prune = 0.0
        self.last_key, self.last_error = "", ""

    def status(self) -> dict:
        return {"enabled": self.enabled, "bucket": self.bucket, "endpoint": self.endpoint,
                "reason": None if self.enabled else "NMS_S3_ACCESS_KEY / NMS_S3_SECRET_KEY not set",
                "uploads": self.uploads, "errors": self.errors, "last_upload": self.last_upload or None,
                "last_key": self.last_key or None, "last_prune": self.last_prune or None,
                "last_error": self.last_error or None}

    def _pending(self, save_dir: str) -> list[str]:
        now = time.time()
        out = []
        for p in sorted(glob.glob(os.path.join(save_dir, "save*.hg")) + glob.glob(os.path.join(save_dir, "accountdata.hg"))):
            try:
                m = os.path.getmtime(p)
            except OSError:
                continue
            if self._seen.get(p) != m and now - m >= SETTLE_S and os.path.getsize(p) > 0:
                out.append(p)
        return out

    def kick(self, save_dir: str):
        """Cheap: start a background run only when something is new or a prune is due."""
        if not self.enabled or not save_dir:
            return
        due = time.time() - self.last_prune >= PRUNE_EVERY_S
        if not due and not self._pending(save_dir):
            return
        with self._lock:
            if self._running:
                return
            self._running = True
        threading.Thread(target=self._run, args=(save_dir, due), daemon=True).start()

    def _run(self, save_dir: str, prune: bool):
        try:
            prefix = os.path.basename(save_dir.rstrip("/"))
            for p in self._pending(save_dir):
                m = os.path.getmtime(p)
                name = os.path.basename(p)
                stem = name[:-3]
                stamp = dt.datetime.fromtimestamp(m, dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                base = f"{prefix}/{stem}/{stamp}"
                with open(p, "rb") as fh:
                    self.s3.put(f"{base}/{name}", fh.read())
                mf = os.path.join(save_dir, "mf_" + name)
                if os.path.exists(mf):
                    with open(mf, "rb") as fh:
                        self.s3.put(f"{base}/mf_{name}", fh.read())
                self._seen[p] = m
                self.uploads += 1
                self.last_upload, self.last_key = time.time(), f"{base}/{name}"
            self._update_current(save_dir, prefix)
            if prune:
                self._prune(prefix)
                self.last_prune = time.time()
            self.last_error = ""
        except Exception as e:                       # never raise into the exporter
            self.errors += 1
            self.last_error = f"{type(e).__name__}: {e}"
        finally:
            with self._lock:
                self._running = False

    def _update_current(self, save_dir: str, prefix: str):
        """The newest save of any slot, always at the same three keys:
        current/save.hg, current/mf_save.hg and current/info.json (which slot
        file it is, its mtime and its versioned key). Overwritten in place, so a
        restore or another tool never has to search for the latest version."""
        saves = [p for p in glob.glob(os.path.join(save_dir, "save*.hg"))
                 if os.path.getsize(p) > 0 and time.time() - os.path.getmtime(p) >= SETTLE_S]
        if not saves:
            return
        p = max(saves, key=os.path.getmtime)
        m = os.path.getmtime(p)
        if self._current == (p, m):
            return
        name = os.path.basename(p)
        stamp = dt.datetime.fromtimestamp(m, dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        with open(p, "rb") as fh:
            data = fh.read()
        self.s3.put("current/save.hg", data)
        mf = os.path.join(save_dir, "mf_" + name)
        if os.path.exists(mf):
            with open(mf, "rb") as fh:
                self.s3.put("current/mf_save.hg", fh.read())
        info = {"file": name, "manifest": "mf_" + name, "slot_file_stem": name[:-3],
                "mtime": m, "mtime_utc": stamp, "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "version_key": f"{prefix}/{name[:-3]}/{stamp}/{name}",
                "restore": f"copy current/save.hg to {name} and current/mf_save.hg to mf_{name}"}
        self.s3.put("current/info.json", json.dumps(info, indent=1).encode())
        self._current = (p, m)

    def _prune(self, prefix: str):
        keys = self.s3.list(prefix + "/")
        versions: dict = {}
        for k in keys:
            parts = k.split("/")
            if len(parts) == 4:
                versions.setdefault(parts[1], {}).setdefault(parts[2], []).append(k)
        now = time.time()
        for stem, by_stamp in versions.items():
            keep = to_keep(list(by_stamp), now)
            for stamp, ks in by_stamp.items():
                if stamp not in keep:
                    for k in ks:
                        self.s3.delete(k)
