#!/usr/bin/env python3
"""Refresh /etc/nms-exporter/s3.env and db.env from OpenBao. Standard library only; run as root.

Logs in with the `holly` AppRole (role_id and secret_id in /etc/nms-exporter/bao/,
root-only), reads kv/garage/nms-saves (the save backup's S3 key) and kv/nms-db (the
nms-db Postgres login, homelab-k8s infra/nms-db), and rewrites each env file (mode 600)
only when it changed, restarting nms-exporter@<user> so the new values are picked up.
A secret the policy does not grant yet is skipped with a message, not fatal. The token
is short-lived (15 min) and never stored. Run by nms-bao-sync.timer.

    NMS_BAO_ADDR      default https://openbao.bobs.toys
    NMS_BAO_DIR       default /etc/nms-exporter/bao   (role_id, secret_id)
    NMS_S3_ENV        default /etc/nms-exporter/s3.env
    NMS_DB_ENV        default /etc/nms-exporter/db.env
    NMS_DB_HOST       default 172.23.69.102   (nms-db-rw-lb)
    NMS_EXPORTER_UNIT default nms-exporter@bob.service
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

ADDR = os.environ.get("NMS_BAO_ADDR", "https://openbao.bobs.toys")
BAO_DIR = os.environ.get("NMS_BAO_DIR", "/etc/nms-exporter/bao")
ENV_FILE = os.environ.get("NMS_S3_ENV", "/etc/nms-exporter/s3.env")
UNIT = os.environ.get("NMS_EXPORTER_UNIT", "nms-exporter@bob.service")
DB_ENV_FILE = os.environ.get("NMS_DB_ENV", "/etc/nms-exporter/db.env")
DB_HOST = os.environ.get("NMS_DB_HOST", "172.23.69.102")
SECRET = "kv/data/garage/nms-saves"
DB_SECRET = "kv/data/nms-db"


def call(method, path, body=None, token=None):
    headers = {"content-type": "application/json"}
    if token:
        headers["X-Vault-Token"] = token
    req = urllib.request.Request(ADDR + path, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read() or b"{}")


def write_env(path, content) -> bool:
    """Write `content` to `path` (mode 600) if it differs; True when it changed."""
    try:
        with open(path) as fh:
            if fh.read() == content:
                return False
    except FileNotFoundError:
        pass
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(content)
    os.replace(tmp, path)
    return True


def main() -> int:
    with open(os.path.join(BAO_DIR, "role_id")) as fh:
        role_id = fh.read().strip()
    with open(os.path.join(BAO_DIR, "secret_id")) as fh:
        secret_id = fh.read().strip()
    token = call("POST", "/v1/auth/approle/login", {"role_id": role_id, "secret_id": secret_id})["auth"]["client_token"]
    try:
        data = call("GET", "/v1/" + SECRET, token=token)["data"]["data"]
        try:
            dbs = call("GET", "/v1/" + DB_SECRET, token=token)["data"]["data"]
        except urllib.error.HTTPError as e:
            print(f"{DB_SECRET}: HTTP {e.code} (not created yet, or not in the holly policy); db.env left as is")
            dbs = None
    finally:
        try:
            call("POST", "/v1/auth/token/revoke-self", {}, token=token)
        except Exception:
            pass
    changed = []
    if write_env(ENV_FILE, f"# written by nms-bao-sync from OpenBao {SECRET}; do not edit by hand\n"
                           f"NMS_S3_ACCESS_KEY={data['access_key_id']}\nNMS_S3_SECRET_KEY={data['secret_access_key']}\n"):
        changed.append("s3.env")
    # libpq's own variables: psycopg reads them with no connection string. TLS required;
    # the server certificate is CNPG's self-signed CA, not verified (LAN, MetalLB IP).
    if dbs and write_env(DB_ENV_FILE, f"# written by nms-bao-sync from OpenBao {DB_SECRET}; do not edit by hand\n"
                                      f"PGHOST={DB_HOST}\nPGPORT=5432\nPGDATABASE=nms\nPGUSER={dbs['db_username']}\n"
                                      f"PGPASSWORD={dbs['db_password']}\nPGSSLMODE=require\n"):
        changed.append("db.env")
    if not changed:
        print("s3.env and db.env unchanged")
        return 0
    subprocess.run(["systemctl", "try-restart", UNIT], check=False)
    print(f"{', '.join(changed)} updated, {UNIT} restarted")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"nms-bao-sync failed: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
