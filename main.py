"""
main.py — Orchestrator: fetch → curate → generate → git push.

Usage:
  python main.py            # full run
  python main.py --dry-run  # skip git push (useful for testing)
  python main.py --no-push  # same as --dry-run
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from fetch import fetch_all
from curate import curate
from generate import generate_html
from podcast import generate_podcast

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")

REPO_DIR = Path(__file__).parent


def _git(args: list, repo_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=repo_dir, capture_output=True, text=True)


def _remote_url(repo_dir: Path) -> str:
    if os.environ.get("GIT_SSH_COMMAND"):
        return "git@github.com:koustubh25/morning-brief.git"
    return _git(["git", "remote", "get-url", "origin"], repo_dir).stdout.strip()


def git_pull(repo_dir: Path) -> None:
    """Pull latest before generating files so there are no conflicts on push."""
    remote_url = _remote_url(repo_dir)
    pull = _git(["git", "pull", "--rebase", remote_url, "main"], repo_dir)
    if pull.returncode != 0:
        log.warning("git pull failed (proceeding anyway): %s", pull.stderr.strip())
    else:
        log.info("git pull --rebase OK")


def git_commit_and_push(repo_dir: Path) -> None:
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    remote_url = _remote_url(repo_dir)

    # Stage generated files
    files_to_add = ["output/index.html", "output/brief.json"]
    if (repo_dir / "output" / "podcast.mp3").exists():
        files_to_add.append("output/podcast.mp3")
    if (repo_dir / "output" / "seen.json").exists():
        files_to_add.append("output/seen.json")
    read_json = repo_dir / "output" / "read.json"
    if read_json.exists():
        files_to_add.append("output/read.json")
    archive_file = repo_dir / "archive" / f"{date_str}.md"
    if archive_file.exists():
        files_to_add.append(str(archive_file.relative_to(repo_dir)))

    add = _git(["git", "add"] + files_to_add, repo_dir)
    if add.returncode != 0:
        log.warning("git add warning: %s", add.stderr.strip())

    # `git diff --cached --quiet` exits 0 if nothing is staged, 1 if there are changes
    if _git(["git", "diff", "--cached", "--quiet"], repo_dir).returncode == 0:
        log.info("No changes to commit — digest unchanged.")
        return

    commit_msg = f"chore: digest {date_str}"
    commit = _git(["git", "commit", "-m", commit_msg], repo_dir)
    if commit.returncode != 0:
        raise RuntimeError(f"git commit failed: {commit.stderr.strip()}")
    log.info("Committed: %s", commit_msg)

    push = _git(["git", "push", "--set-upstream", remote_url, "HEAD:refs/heads/main"], repo_dir)
    if push.returncode != 0:
        raise RuntimeError(f"git push failed: {push.stderr.strip()}")
    log.info("Pushed to origin/main — GitHub Actions will deploy.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Morning Brief generator")
    parser.add_argument("--dry-run", "--no-push", action="store_true", help="Skip git push")
    parser.add_argument("--converse", action="store_true", help="Launch voice debate partner after generating brief")
    parser.add_argument("--test", action="store_true", help="Fast mode: 1 batch of 5 items, no HN, 1 GN query")
    args = parser.parse_args()

    # Ensure we run from the repo root so relative config paths work
    os.chdir(REPO_DIR)

    log.info("=== Morning Brief — %s ===", datetime.now(timezone.utc).strftime("%a %-d %b %Y"))

    if not args.dry_run:
        log.info("Step 0: Pulling latest from remote (before generating files)…")
        git_pull(REPO_DIR)

    log.info("Step 1: Fetching candidates…")
    candidates = fetch_all(test_mode=args.test)
    if not candidates:
        log.error("No candidates fetched. Aborting.")
        return 1

    # Load URLs marked as read in the soft-skills frontend
    read_path = Path("output/read.json")
    read_urls = set()
    if read_path.exists():
        try:
            with open(read_path) as f:
                read_urls = set(json.load(f))
            log.info("Loaded %d read URLs to exclude", len(read_urls))
        except Exception:
            pass

    log.info("Step 2: Curating with Claude…")
    selected = curate(candidates, top_n=3 if args.test else 9, exclude_urls=read_urls)
    if not selected:
        log.error("No items selected after curation. Aborting.")
        return 1

    log.info("Step 3: Generating podcast…")
    try:
        generate_podcast(selected)
    except Exception:
        log.exception("Podcast generation failed (non-fatal, continuing)")

    log.info("Step 4: Generating HTML…")
    generate_html(selected)

    if args.dry_run:
        log.info("--dry-run: skipping git commit/push.")
        log.info("Open output/index.html to preview.")
    else:
        log.info("Step 5: Committing and pushing…")
        git_commit_and_push(REPO_DIR)

    log.info("Done. %d items in today's brief.", len(selected))

    if args.converse:
        log.info("Launching voice debate partner…")
        import converse
        converse.main()

    return 0


if __name__ == "__main__":
    sys.exit(main())
