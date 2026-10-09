"""headersHelper for the BigQuery remote MCP server (https://bigquery.googleapis.com/mcp).

Claude Code runs this on every connection and expects a JSON object of headers on stdout
within 10 seconds. It turns the gcloud sign-in (`gcloud auth login --update-adc`) into a
bearer token, so no OAuth client or client secret has to be created or stored.

Token caching: gcloud takes 2-4 s on Windows, so the token is cached for 45 minutes
(Google tokens last 60). A second call within 2 minutes is treated as a retry after a
401 and refreshes the token instead of serving the cached one.
"""

import json
import os
import shutil
import subprocess
import sys
import time

CACHE = os.path.join(os.path.expanduser("~"), ".claude", "hooks", ".bigquery-token.json")
CACHE_TTL = 45 * 60
RETRY_WINDOW = 120
FALLBACK_PROJECT = "bookandry"


def gcloud_path():
    for name in ("gcloud", "gcloud.cmd"):
        found = shutil.which(name)
        if found:
            return found
    for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            candidate = os.path.join(base, "Google", "Cloud SDK", "google-cloud-sdk", "bin", "gcloud.cmd")
            if os.path.exists(candidate):
                return candidate
    return "gcloud"


def gcloud_config_dir():
    if os.name == "nt":
        return os.path.join(os.environ.get("APPDATA", ""), "gcloud")
    return os.path.join(os.path.expanduser("~"), ".config", "gcloud")


def quota_project():
    """The project that is billed/quota'd for the call: ADC quota project, then gcloud's
    default project, then the fallback."""
    cfg = gcloud_config_dir()
    try:
        with open(os.path.join(cfg, "application_default_credentials.json"), encoding="utf-8") as f:
            project = json.load(f).get("quota_project_id")
            if project:
                return project
    except (OSError, ValueError):
        pass
    try:
        with open(os.path.join(cfg, "configurations", "config_default"), encoding="utf-8") as f:
            for line in f:
                key, _, value = line.partition("=")
                if key.strip() == "project" and value.strip():
                    return value.strip()
    except OSError:
        pass
    return FALLBACK_PROJECT


def read_cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_cache(data):
    """Owner-only file: the token is a live bearer credential for one hour."""
    os.makedirs(os.path.dirname(CACHE), mode=0o700, exist_ok=True)
    tmp = CACHE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, CACHE)
    try:
        os.chmod(CACHE, 0o600)
    except OSError:
        pass


def fresh_token():
    try:
        result = subprocess.run(
            [gcloud_path(), "auth", "application-default", "print-access-token"],
            capture_output=True,
            text=True,
            timeout=8,
            shell=False,
        )
    except FileNotFoundError:
        sys.stderr.write("gcloud not found; install the Google Cloud CLI (winget install Google.CloudSDK)\n")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        sys.stderr.write("gcloud took longer than 8 s\n")
        sys.exit(1)
    if result.returncode != 0 or not result.stdout.strip():
        sys.stderr.write((result.stderr.strip() or "gcloud returned no token") + "; run: gcloud auth login --update-adc\n")
        sys.exit(1)
    return result.stdout.strip()


def main():
    now = time.time()
    cache = read_cache()
    token = None
    if cache and now - cache.get("issued", 0) < CACHE_TTL and now - cache.get("served", 0) > RETRY_WINDOW:
        token = cache["token"]
    if token is None:
        token = fresh_token()
        cache = {"token": token, "issued": now}
    cache["served"] = now
    try:
        write_cache(cache)
    except OSError:
        pass
    sys.stdout.write(json.dumps({"Authorization": "Bearer " + token, "x-goog-user-project": quota_project()}))


if __name__ == "__main__":
    main()
