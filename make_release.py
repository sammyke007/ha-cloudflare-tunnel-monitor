#!/usr/bin/env python3
import subprocess
import datetime
import json
import re
import sys
from pathlib import Path

MANIFEST_PATH = Path("custom_components/cloudflare_tunnel_monitor/manifest.json")
README_PATH = Path("README.md")


# -----------------------------
# Helpers
# -----------------------------
def run_output(cmd):
    """Run a command and return stdout."""
    return subprocess.check_output(cmd, text=True).strip()


def run(cmd):
    """Run a command that must succeed."""
    subprocess.run(cmd, check=True)


def ensure_clean_worktree():
    """Stop if working tree contains uncommitted changes."""
    status = run_output(["git", "status", "--porcelain"])
    if status:
        print("❌ Working tree is niet clean. Commit of stash je wijzigingen eerst.")
        print(status)
        sys.exit(1)


# -----------------------------
# Versioning
# -----------------------------
def get_next_tag():
    """Determine next vYYYY.MM.X release tag."""
    now = datetime.datetime.now()
    prefix = f"v{now.year}.{now.month:02d}"

    tags_raw = run_output(["git", "tag"])
    tags = tags_raw.splitlines() if tags_raw else []

    # Filter tags from this month: v2025.12.0, v2025.12.1
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


# -----------------------------
# Update manifest.json
# -----------------------------
def update_manifest(version_str):
    print("🔧 manifest.json updaten...")

    # Veilig als UTF-8 lezen & schrijven
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["version"] = version_str

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=4), encoding="utf-8")
    run(["git", "add", str(MANIFEST_PATH)])

    print(f"   ✔ manifest.json → version = {version_str}")


# -----------------------------
# Update README.md
# -----------------------------
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

    # Patronen met 'v2025.12.0'
    updated = re.sub(r"v20\d{2}\.\d{2}\.\d+", new_tag, updated)

    # Patronen met '2025.12.0' (zonder 'v')
    updated = re.sub(r"20\d{2}\.\d{2}\.\d+", version_str, updated)

    if updated != readme:
        README_PATH.write_text(updated, encoding="utf-8")
        run(["git", "add", str(README_PATH)])
        print("   ✔ README.md bijgewerkt")
    else:
        print("   ℹ Geen versiepatroon gevonden — prima.")


# -----------------------------
# Changelog genereren
# -----------------------------
def build_changelog(new_tag, all_tags):
    print("📝 Changelog genereren...")

    previous_tag = None

    if all_tags:
        sorted_tags = sorted(
            all_tags,
            key=lambda s: list(map(int, re.findall(r"\d+", s)))
        )
        previous_tag = sorted_tags[-1]

    if previous_tag:
        print(f"   Vorige tag: {previous_tag}")
        changelog = run_output([
            "git", "log", f"{previous_tag}..HEAD", "--pretty=format:- %s"
        ])
    else:
        print("   Geen vorige tag gevonden → gebruik volledige geschiedenis")
        changelog = run_output(["git", "log", "--pretty=format:- %s"])

    changelog = changelog.strip() or "- No changes listed"

    text = f"## Changelog for {new_tag}\n\n{changelog}\n"
    print()
    print(text)
    return text


# -----------------------------
# Main
# -----------------------------
def main():
    ensure_clean_worktree()

    new_tag, all_tags = get_next_tag()
    version_str = new_tag.lstrip("v")  # manifest heeft geen 'v'

    print(f"\n🚀 Nieuwe release-tag wordt: {new_tag}")
    print(f"   (manifest.json versie: {version_str})\n")

    # 1. manifest.json bijwerken
    update_manifest(version_str)

    # 2. README.md bijwerken
    update_readme(new_tag, version_str)

    # 3. Changelog genereren
    changelog_text = build_changelog(new_tag, all_tags)

    # 4. Commit maken
    print("💾 Commit maken...")
    run(["git", "commit", "-m", f"Release {version_str}"])

    # 5. Annotated tag met changelog
    print("🏷️ Tag aanmaken...")
    run(["git", "tag", "-a", new_tag, "-m", changelog_text])

    # 6. Push commit + tag
    print("⬆️ Pushen van commit + tag...")
    run(["git", "push"])
    run(["git", "push", "origin", new_tag])

    print("\n🎉 Klaar!")
    print(f"👉 Nieuwe tag gepusht: {new_tag}")
    print("👉 GitHub Actions release workflow zal nu automatisch starten.")


if __name__ == "__main__":
    main()
