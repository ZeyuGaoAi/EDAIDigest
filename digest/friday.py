"""Run the reviewed digest on Friday and open an unsent Outlook draft."""

from __future__ import annotations

import argparse
import fcntl
import os
import plistlib
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from digest.config import DRAFTS_DIR, ROOT, SETTINGS_PATH
from digest.settings import load_settings


LABEL = "eu.esac.early-cancer-digest.friday"
ESAC_LOGO_URL = "https://esac-network.eu/wp-content/uploads/2025/04/ESAC-LOGO-LARGE-300x169.png"
STATE_DIR = Path.home() / "Library" / "Application Support" / "AI Early Cancer Digest"
LAUNCH_AGENT = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
PROMPT = """Update the AI for Early Cancer Digest for today's Friday issue. Read README.md and
the current settings. Ingest sources and review every plausible paper abstract and opportunity
description for early-cancer-detection relevance, rejecting false positives. Generate the
reviewed HTML and text email drafts for today, rebuild the site archive, run tests, and push
the generated issue and site to origin/main if checks pass. Preserve unrelated local edits.
Report counts and source errors. Do not send email or operate any mail client: the launcher
opens an unsent compose window for the human reviewer after you finish.
"""


def eligible_issue(now: datetime) -> str | None:
    local = now.astimezone(ZoneInfo("Europe/London"))
    if local.weekday() != 4 or local.hour < 9:
        return None
    return local.date().isoformat()


def launch_agent_data(python: str, repo: Path) -> bytes:
    data = {
        "Label": LABEL,
        "ProgramArguments": [python, "-m", "digest.friday", "run"],
        "WorkingDirectory": str(repo),
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


def prepare_compose_html(draft: Path, output: Path, logo: Path) -> Path:
    html = draft.read_text(encoding="utf-8")
    if ESAC_LOGO_URL in html:
        if not logo.is_file():
            try:
                with urlopen(ESAC_LOGO_URL, timeout=15) as response:
                    image = response.read(500_001)
                if len(image) > 500_000 or not image.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ValueError("ESAC logo is not a small PNG")
                logo.write_bytes(image)
            except (OSError, ValueError):
                # The mail composer must not try to fetch a remote image while pasting.
                html = re.sub(r"<img\b[^>]*\bsrc=\"" + re.escape(ESAC_LOGO_URL)
                              + r"\"[^>]*>", "<strong>ESAC</strong>", html)
        if logo.is_file():
            html = html.replace(f'src="{ESAC_LOGO_URL}"', f'src="{logo.as_uri()}"')
    output.write_text(html, encoding="utf-8")
    return output


def open_outlook_draft(issue: str, draft: Path, marker: Path) -> None:
    settings = load_settings(SETTINGS_PATH)
    distribution = settings.get("distribution", {})
    recipients = distribution.get("recipient_emails", [])
    if not isinstance(recipients, list) or not recipients:
        raise ValueError("No recipient emails configured in Setup")
    sender = distribution.get("sender_email", "zg323@cam.ac.uk")
    subject = distribution.get("email_subject", "AI for Early Cancer Digest | {date}")
    subject = subject.replace("{date}", issue)
    compose_html = prepare_compose_html(
        draft, STATE_DIR / f"compose-{issue}.html", STATE_DIR / "esac-logo.png"
    )
    prompt = f"""Open an UNSENT rich-text email draft in Microsoft Outlook for human review.
Use the computer-use tool, not mailto or the Apple Mail sharing service. The fully rendered HTML
is in {compose_html}. Read the complete file, then use cua_repl app.paste(html, {{format:'html'}})
in the Outlook compose body. Switch to the School profile and verify From is {sender}.
To: {', '.join(recipients)}. Subject: {subject}.
The HTML references a local ESAC logo; verify the compose body has an actual image, headings,
and working links, not literal HTML tags or just the word ESAC. Leave the compose window open.
NEVER click Send or transmit the email. If Outlook is unavailable, try Apple Mail only if it can
preserve the same rich body and sender. Only after inspecting the filled compose window, write
the text 'opened' to {marker} using a shell command. If you cannot verify it, do not write the
marker; report the problem instead.
"""
    log = STATE_DIR / f"outlook-{issue}.log"
    with log.open("w") as output:
        result = subprocess.run(
            ["codex", "exec", "-m", "gpt-6-sol", "--approve-for-me",
             "--cd", str(ROOT), "-"],
            input=prompt, text=True, stdout=output, stderr=subprocess.STDOUT,
            cwd=ROOT, check=False,
        )
    if result.returncode or not marker.exists():
        raise RuntimeError(f"Could not verify the Outlook draft; see {log}")
    notify("Rich digest draft opened in Outlook. Review it and click Send yourself.")


def run(now: datetime | None = None) -> None:
    issue = eligible_issue(now or datetime.now().astimezone())
    if issue is None:
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with (STATE_DIR / "friday.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        marker = ROOT / "data" / f".friday-mail-opened-{issue}"
        if marker.exists():
            return
        draft = DRAFTS_DIR / f"{issue}.html"
        if not draft.is_file():
            log = STATE_DIR / f"codex-{issue}.log"
            with log.open("w") as output:
                result = subprocess.run(
                    ["codex", "exec", "-m", "gpt-6-sol", "--approve-for-me",
                     "--cd", str(ROOT), "-"],
                    input=PROMPT, text=True, stdout=output, stderr=subprocess.STDOUT,
                    cwd=ROOT, check=False,
                )
            if result.returncode or not draft.is_file():
                notify(f"Friday digest failed. Check {log} and run it manually.")
                raise RuntimeError(f"Codex did not generate {draft}; see {log}")
        try:
            open_outlook_draft(issue, draft, marker)
        except Exception:
            notify("Digest generated, but Outlook draft could not be verified. Use the local Setup page.")
            raise


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
