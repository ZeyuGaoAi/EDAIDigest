"""Generate and publish the reviewed digest on Friday."""

from __future__ import annotations

import argparse
import fcntl
import os
import plistlib
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from digest.config import DRAFTS_DIR, ROOT


LABEL = "eu.esac.early-cancer-digest.friday"
STATE_DIR = Path.home() / "Library" / "Application Support" / "AI Early Cancer Digest"
LAUNCH_AGENT = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
PROMPT = """Update the AI for Early Cancer Digest for today's Friday issue. Read README.md and
the current settings. Ingest sources and review every plausible paper abstract and opportunity
description for early-cancer-detection relevance, rejecting false positives. Generate the
reviewed HTML and text email drafts for today, rebuild the site archive, run tests, and push
the generated issue and site to origin/main if checks pass. Preserve unrelated local edits.
Report counts and source errors. Do not send email or operate any mail client. The user
will prepare and send the email manually after reviewing the updated web page.
"""


def eligible_issue(now: datetime) -> str | None:
    local = now.astimezone(ZoneInfo("Europe/London"))
    if local.weekday() != 4 or local.hour < 9:
        return None
    return local.date().isoformat()


def launch_agent_data(python: str, repo: Path) -> bytes:
    terminal_command = f"cd {shlex.quote(str(repo))} && {shlex.quote(python)} -m digest.friday run"
    apple_script = ('on run argv\n tell application "Terminal"\n activate\n'
                    ' do script (item 1 of argv)\n end tell\nend run')
    friday = '[ "$(TZ=Europe/London date +%u)" = 5 ] && [ "$(TZ=Europe/London date +%H)" -ge 9 ]'
    command = (f"if {friday}; then /usr/bin/osascript -e {shlex.quote(apple_script)} "
               f"{shlex.quote(terminal_command)}; fi")
    data = {
        "Label": LABEL,
        "ProgramArguments": ["/bin/bash", "-c", command],
        "WorkingDirectory": "/tmp",
        "RunAtLoad": True,
        "StartCalendarInterval": {"Weekday": 5, "Hour": 9, "Minute": 0},
        "StandardOutPath": str(STATE_DIR / "friday.log"),
        "StandardErrorPath": str(STATE_DIR / "friday-error.log"),
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        },
    }
    return plistlib.dumps(data)


def install() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LAUNCH_AGENT.parent.mkdir(parents=True, exist_ok=True)
    LAUNCH_AGENT.write_bytes(launch_agent_data(sys.executable, ROOT))
    target = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", target, str(LAUNCH_AGENT)],
                   capture_output=True, check=False)
    subprocess.run(["launchctl", "bootstrap", target, str(LAUNCH_AGENT)], check=True)
    subprocess.run(["launchctl", "enable", f"{target}/{LABEL}"], check=True)
    print(f"Installed Friday login task: {LAUNCH_AGENT}")


def notify(message: str) -> None:
    script = 'on run argv\n display notification (item 1 of argv) with title "Early Cancer Digest"\nend run'
    subprocess.run(["osascript", "-e", script, message], check=False, capture_output=True)


def run(now: datetime | None = None) -> None:
    issue = eligible_issue(now or datetime.now().astimezone())
    if issue is None:
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with (STATE_DIR / "friday.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        marker = STATE_DIR / f"site-updated-{issue}"
        if marker.exists():
            return
        draft = DRAFTS_DIR / f"{issue}.html"
        log = STATE_DIR / f"codex-{issue}.log"
        with log.open("w") as output:
            result = subprocess.run(
                ["codex", "exec", "-m", "gpt-6-sol", "--approve-for-me",
                 "--cd", str(ROOT), "-"],
                input=PROMPT, text=True, stdout=output, stderr=subprocess.STDOUT,
                cwd=ROOT, check=False,
            )
        archive = ROOT / "docs" / "index.html"
        if result.returncode or not draft.is_file() or not archive.is_file() or issue not in archive.read_text(encoding="utf-8"):
            notify(f"Friday digest failed. Check {log} and run it manually.")
            raise RuntimeError(f"Could not verify the Friday site update; see {log}")
        marker.write_text("updated\n", encoding="utf-8")
        notify("Digest web page updated. Review the issue and prepare the email manually.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("install", "run", "check"))
    args = parser.parse_args()
    if args.command == "install":
        install()
    elif args.command == "check":
        print(f"LaunchAgent: {'installed' if LAUNCH_AGENT.exists() else 'not installed'}")
        print(f"This Friday: {eligible_issue(datetime.now().astimezone()) or 'not eligible yet'}")
    else:
        run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
