#!/usr/bin/env python3
"""
Build a SideStore / AltStore source (apps.json)
from latest GitHub releases of configured upstream repos.
Standard library only.
"""

import fnmatch
import json
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "source-config.json")
OUTPUT_PATH = os.path.join(HERE, "apps.json")

API = "https://api.github.com/repos/{repo}/releases?per_page=100"
VERSION_RE = re.compile(r"\d+(?:\.\d+)*")


def fail(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        fail(f"{CONFIG_PATH} not found")
    except json.JSONDecodeError as e:
        fail(f"source-config.json is not valid JSON: {e}")


def fetch_releases(repo):
    url = API.format(repo=repo)
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "sidestore-source-builder",
        },
    )
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        fail(f"GitHub API returned {e.code} for {repo}: {e.read()[:200]!r}")
    except urllib.error.URLError as e:
        fail(f"could not reach GitHub API: {e.reason}")


def pick_asset(release, pattern):
    for asset in release.get("assets", []):
        if fnmatch.fnmatch(asset.get("name", ""), pattern):
            return asset
    return None


def version_from_tag(tag):
    tag = tag or ""
    m = VERSION_RE.search(tag)
    return m.group(0) if m else tag or "0"


def normalize_date(value):
    return value or "1970-01-01T00:00:00Z"


def build_app_entry(repo_cfg, releases):
    app_meta = repo_cfg.get("app", {})
    pattern = repo_cfg.get("assetPattern", "*.ipa")
    include_pre = bool(repo_cfg.get("includePrereleases", False))
    max_versions = int(repo_cfg.get("maxVersions", 5))

    versions = []
    for release in releases:
        if release.get("draft"):
            continue
        if release.get("prerelease") and not include_pre:
            continue

        asset = pick_asset(release, pattern)
        if asset is None:
            print(f"skip {release.get('tag_name')}: no asset matching {pattern!r}")
            continue

        tag = release.get("tag_name") or ""
        versions.append(
            {
                "version": version_from_tag(tag),
                "buildVersion": tag,
                "date": normalize_date(release.get("published_at")),
                "downloadURL": asset["browser_download_url"],
                "size": asset["size"],
                "localizedDescription": (release.get("body") or "")[:2000],
                "minOSVersion": app_meta.get("minOSVersion", "0.0"),
            }
        )

        if len(versions) >= max_versions:
            break

    if not versions:
        print(f"warning: no valid IPA releases found for {repo_cfg['repo']}")
        return None

    app = {
        "name": app_meta.get("name", repo_cfg["repo"].split("/")[-1]),
        "bundleIdentifier": app_meta["bundleIdentifier"],
        "developerName": app_meta.get("developerName", repo_cfg["repo"].split("/")[0]),
        "subtitle": app_meta.get("subtitle", ""),
        "localizedDescription": app_meta.get("localizedDescription", ""),
        "iconURL": app_meta.get("iconURL", ""),
        "tintColor": app_meta.get("tintColor", "#6C5CE7"),
        "category": app_meta.get("category", "utilities"),
        "versions": versions,
    }
    if "screenshotURLs" in app_meta:
        app["screenshotURLs"] = app_meta["screenshotURLs"]

    return app


def main():
    config = load_config()
    source_meta = config["source"]
    repos = config.get("repos", [])
    if not repos:
        fail("source-config.json has no 'repos'")

    apps = []
    for repo_cfg in repos:
        repo = repo_cfg.get("repo", "")
        if "/" not in repo:
            fail(f"invalid repo: {repo!r} (expected owner/name)")
        releases = fetch_releases(repo)
        app = build_app_entry(repo_cfg, releases)
        if app:
            apps.append(app)

    output = {
        "name": source_meta["name"],
        "identifier": source_meta["identifier"],
        "subtitle": source_meta.get("subtitle", ""),
        "description": source_meta.get("description", ""),
        "website": source_meta.get("website", ""),
        "iconURL": source_meta.get("iconURL", ""),
        "tintColor": source_meta.get("tintColor", "#6C5CE7"),
        "apps": apps,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"written {OUTPUT_PATH} with {len(apps)} app(s)")


if __name__ == "__main__":
    main()
