#!/usr/bin/env python3
import subprocess
import datetime
import json
import re
import sys
from pathlib import Path

MANIFEST_PATH = Path("custom_components/cloudflare_tunnel_monitor/manifest.json")
README_PATH = Path("README.md")
RELEASE_BODY_PATH = Path("RELEASE_BODY.md")

REPO_OWNER = "sammyke007"
REPO_NAME = "ha-cloudflare-tunnel-monitor"


def run_output(cmd):
    return subprocess.check_output(cmd, text=True).strip()


def run(cmd):
    subprocess.run(cmd, check=True)


def ensure_clean_worktree():
    status = run_output(["git", "status", "--porcelain"])
    if status:
        print("❌ Working tree is niet clean. Commit of stash je wijzigingen eerst.")
        print(status)
        sys.exit(1)


def get_next_tag():
    now = datetime.datetime.now()
    prefix = f"v{now.year}.{now.month:02d}"

    tags_raw = run_output(["git", "tag"])
    tags = tags_raw.splitlines() if tags_raw else []

    month_tags = [t for t in tags if t.startswith(prefix + ".")]

    max_num = -1
    pattern = re.compile(rf"{prefix}\.(\d+)")
    for t in month_tags:
        m = pattern.match(t)
        if m:
            num = int(m.group(1))
            max_num = max(max_num, num)

    next_num = max_num + 1
    new_tag = f"{prefix}.{next_num}"
    return new_tag, tags


def update_manifest(version_str):
    print("🔧 manifest.json updaten...")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["version"] = version_str
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=4), encoding="utf-8")
    run(["git", "add", str(MANIFEST_PATH)])
    print(f"   ✔ manifest.json → version = {version_str}")


def update_readme(new_tag, version_str):
    if not README_PATH.exists():
        print("ℹ README.md niet gevonden — skipping.")
        return

    print("🔧 README.md versie updaten (indien gevonden)...")
    try:
        readme = README_PATH.read_text(encoding="utf-8")
    except Exception as e:
        print("❌ Kon README.md niet lezen als UTF-8:", e)
        sys.exit(1)

    updated = readme
    updated = re.sub(r"v20\d{2}\.\d{2}\.\d+", new_tag, updated)
    updated = re.sub(r"20\d{2}\.\d{2}\.\d+", version_str, updated)

    if updated != readme:
        README_PATH.write_text(updated, encoding="utf-8")
        run(["git", "add", str(README_PATH)])
        print("   ✔ README.md bijgewerkt")
    else:
        print("   ℹ Geen versiepatroon gevonden — prima.")


def build_changelog(new_tag, all_tags):
    print("📝 Mooie changelog genereren...")

    previous_tag = None
    if all_tags:
        sorted_tags = sorted(
            all_tags,
            key=lambda s: list(map(int, re.findall(r"\d+", s)))
        )
        previous_tag = sorted_tags[-1]

    if previous_tag:
        commits = run_output([
            "git", "log",
            f"{previous_tag}..HEAD",
            "--pretty=format:%s"
        ]).splitlines()
        compare_slug = f"{previous_tag}...{new_tag}"
    else:
        commits = run_output(["git", "log", "--pretty=format:%s"]).splitlines()
        compare_slug = new_tag

    sections = {
        "✨ Features": [],
        "🐛 Fixes": [],
        "📦 Maintenance": [],
        "📚 Documentation": [],
        "🔧 Other": []
    }

    keywords = {
        "✨ Features": ["add", "new", "feature", "improve", "support", "implement", "enable", "introduce"],
        "🐛 Fixes": ["fix", "bug", "issue", "correct", "resolve", "repair", "broken"],
        "📦 Maintenance": ["refactor", "cleanup", "clean", "chore", "optimize", "speed", "perf", "restructure"],
        "📚 Documentation": ["readme", "doc", "docs", "explain", "documentation", "comment"],
    }

    for commit in commits:
        cl = commit.lower().strip()

        if cl.startswith(("feat:", "feature:")):
            sections["✨ Features"].append(commit)
            continue
        if cl.startswith(("fix:", "bug:", "hotfix:")):
            sections["🐛 Fixes"].append(commit)
            continue
        if cl.startswith(("docs:", "doc:", "readme")):
            sections["📚 Documentation"].append(commit)
            continue
        if cl.startswith(("chore:", "refactor:", "clean:", "maint:", "ci:")):
            sections["📦 Maintenance"].append(commit)
            continue

        placed = False
        for section, words in keywords.items():
            if any(word in cl for word in words):
                sections[section].append(commit)
                placed = True
                break

        if not placed:
            sections["🔧 Other"].append(commit)

    body_lines = [f"# Changes in {new_tag}", ""]

    for title, items in sections.items():
        if items:
            body_lines.append(f"## {title}")
            body_lines.extend([f"- {item}" for item in items])
            body_lines.append("")

    compare_url = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/compare/{compare_slug}"
    body_lines.append("---")
    body_lines.append(f"🔗 **Full diff:** [{compare_slug}]({compare_url})")
    body_lines.append("")

    final_body = "\n".join(body_lines)

    # schrijf naar file en voeg toe aan commit
    RELEASE_BODY_PATH.write_text(final_body, encoding="utf-8")
    run(["git", "add", str(RELEASE_BODY_PATH)])

    print(final_body)
    return final_body


def main():
    ensure_clean_worktree()

    new_tag, all_tags = get_next_tag()
    version_str = new_tag.lstrip("v")

    print(f"\n🚀 Nieuwe release-tag wordt: {new_tag}")
    print(f"   (manifest.json versie: {version_str})\n")

    update_manifest(version_str)
    update_readme(new_tag, version_str)
    build_changelog(new_tag, all_tags)

    print("💾 Commit maken...")
    run(["git", "commit", "-m", f"Release {version_str}"])

    print("🏷️ Tag aanmaken...")
    run(["git", "tag", "-a", new_tag, "-m", f"Release {new_tag}"])

    print("⬆️ Pushen van commit + tag...")
    run(["git", "push"])
    run(["git", "push", "origin", new_tag])

    print("\n🎉 Klaar!")
    print(f"👉 Nieuwe tag gepusht: {new_tag}")
    print("👉 GitHub Actions release workflow zal nu automatisch starten.")


if __name__ == "__main__":
    main()
