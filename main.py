"""
main.py — Orchestrator: fetch → curate → generate → git push.

Usage:
  python main.py            # full run
  python main.py --dry-run  # skip git push (useful for testing)
  python main.py --no-push  # same as --dry-run
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import git  # gitpython

from fetch import fetch_all
from curate import curate
from generate import generate_html

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")

REPO_DIR = Path(__file__).parent


def git_commit_and_push(repo_dir: Path) -> None:
    repo = git.Repo(repo_dir)
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    # Stage the generated files
    files_to_add = ["output/index.html", "output/brief.json"]
    if (repo_dir / "output" / "seen.json").exists():
        files_to_add.append("output/seen.json")
    repo.index.add(files_to_add)

    if not repo.index.diff("HEAD"):
        log.info("No changes to commit — digest unchanged.")
        return

    commit_msg = f"chore: digest {date_str}"
    repo.index.commit(commit_msg)
    log.info("Committed: %s", commit_msg)

    origin = repo.remotes.origin
    origin.push(refspec="HEAD:refs/heads/main", set_upstream=True)
    log.info("Pushed to origin/main — GitHub Actions will deploy.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Morning Brief generator")
    parser.add_argument("--dry-run", "--no-push", action="store_true", help="Skip git push")
    parser.add_argument("--converse", action="store_true", help="Launch voice debate partner after generating brief")
    args = parser.parse_args()

    # Ensure we run from the repo root so relative config paths work
    os.chdir(REPO_DIR)

    log.info("=== Morning Brief — %s ===", datetime.now(timezone.utc).strftime("%a %-d %b %Y"))

    log.info("Step 1: Fetching candidates…")
    candidates = fetch_all()
    if not candidates:
        log.error("No candidates fetched. Aborting.")
        return 1

    log.info("Step 2: Curating with Claude…")
    selected = curate(candidates)
    if not selected:
        log.error("No items selected after curation. Aborting.")
        return 1

    log.info("Step 3: Generating HTML…")
    generate_html(selected)

    if args.dry_run:
        log.info("--dry-run: skipping git commit/push.")
        log.info("Open output/index.html to preview.")
    else:
        log.info("Step 4: Committing and pushing…")
        git_commit_and_push(REPO_DIR)

    log.info("Done. %d items in today's brief.", len(selected))

    if args.converse:
        log.info("Launching voice debate partner…")
        import converse
        converse.main()

    return 0


if __name__ == "__main__":
    sys.exit(main())
