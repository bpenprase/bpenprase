#!/usr/bin/env python3
"""
sync_to_drive.py — push each channel's digest into a Google Doc in Drive.

Why this exists
---------------
NotebookLM automatically re-syncs Google Drive sources (Docs/Sheets/Slides):
when the underlying file changes, any notebook using it updates to match. So if
this script rewrites one Google Doc per channel every day, a NotebookLM notebook
that has those Docs as sources will stay current with no manual step.

It reads the digest that build_digest.py already produced (data/digest.json) and,
for each channel, replaces the contents of a Google Doc named e.g.
"Full Planet — Synthetic Biology" inside your target Drive folder. Docs are
created on first run and reused (found by name) afterwards, so the same file —
and therefore the same NotebookLM source — persists day to day.

Credentials
-----------
Authentication uses a Google *service account*. The workflow provides the
service-account JSON key via the GOOGLE_SERVICE_ACCOUNT_JSON environment
variable (set from a GitHub secret). The target folder is given by
DRIVE_FOLDER_ID. If either is missing, the script prints a notice and exits 0
(success) so it never breaks the main build.

Required scopes: https://www.googleapis.com/auth/drive  (create/find/update Docs)
The target Drive folder must be shared with the service account's email address
as an Editor (see the setup instructions).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DIGEST = Path(__file__).parent / "data" / "digest.json"

# The Drive folder to write the Docs into (from the folder's URL). Can be
# overridden with the DRIVE_FOLDER_ID environment variable.
DEFAULT_FOLDER_ID = "1btSSbIYAVNs6eF3R9aX5DxfSGAxROniv"

# Clean, stable Doc titles per channel key. The title is how we find the Doc
# again on later runs, so DON'T change these once your notebook points at them.
DOC_TITLES = {
    "ai": "Full Planet — Artificial Intelligence",
    "materials": "Full Planet — Advanced Materials",
    "synbio": "Full Planet — Synthetic Biology",
    "energywater": "Full Planet — Energy & Water",
    "spaceexploration": "Full Planet — Space Exploration",
    "astronomy": "Full Planet — Astronomy & Astrophysics",
}


def log(msg: str) -> None:
    print(f"    [drive] {msg}")


def build_doc_text(channel: dict, generated_human: str) -> str:
    """Render one channel's stories into plain text for a Google Doc.

    NotebookLM reads the Doc's text, so we include the headline, source, date,
    a short summary, and — importantly — the URL, so the notebook can cite and
    follow each story.
    """
    lines = [
        channel["name"],
        f"Full Planet digest — updated {generated_human}",
        f"{len(channel['items'])} stories",
        "=" * 60,
        "",
    ]
    for it in channel["items"]:
        title = it.get("title", "").strip()
        source = it.get("source", "").strip()
        link = it.get("link", "").strip()
        summary = (it.get("summary") or "").strip()
        published = (it.get("published") or "")[:10]  # YYYY-MM-DD
        region = "  [around the world]" if it.get("regional") else ""

        lines.append(title + region)
        meta = " · ".join(p for p in (source, published) if p)
        if meta:
            lines.append(meta)
        if summary:
            lines.append(summary)
        if link:
            lines.append(link)
        lines.append("")  # blank line between stories

    # Consolidated list of all URLs at the end — easy to copy in one block for
    # adding to NotebookLM or other tools.
    all_urls = [it.get("link", "").strip() for it in channel["items"] if it.get("link")]
    lines.append("=" * 60)
    lines.append("ALL STORY URLS")
    lines.append("=" * 60)
    lines.extend(all_urls)
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    folder_id = os.environ.get("DRIVE_FOLDER_ID", DEFAULT_FOLDER_ID)
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

    if not sa_json:
        log("GOOGLE_SERVICE_ACCOUNT_JSON not set — skipping Drive sync. "
            "(This is fine; the website build already succeeded.)")
        return 0

    # Import Google libraries only when we actually have credentials, so the
    # main build doesn't need them installed unless Drive sync is in use.
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
    except ImportError:
        log("google-api-python-client not installed — skipping Drive sync.")
        return 0

    try:
        info = json.loads(sa_json)
    except json.JSONDecodeError as e:
        log(f"GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON: {e}")
        return 0

    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive"]
    )
    drive = build("drive", "v3", credentials=creds)
    docs = build("docs", "v1", credentials=creds)

    digest = json.loads(DIGEST.read_text(encoding="utf-8"))
    generated_human = digest.get("generated_human", "")

    for channel in digest["channels"]:
        key = channel["key"]
        title = DOC_TITLES.get(key, f"Full Planet — {channel['name']}")
        body_text = build_doc_text(channel, generated_human)

        try:
            doc_id = find_or_create_doc(drive, folder_id, title)
            replace_doc_text(docs, doc_id, body_text)
            log(f"updated '{title}' ({len(channel['items'])} stories)")
        except FileNotFoundError as e:
            log(f"SKIP '{title}': {e}")
        except HttpError as e:
            log(f"ERROR updating '{title}': {e}")

    log("Drive sync complete.")
    return 0


def find_or_create_doc(drive, folder_id: str, title: str) -> str:
    """Return the ID of the Doc named `title` in `folder_id`.

    IMPORTANT: this NO LONGER creates the Doc. A service account has no Drive
    storage quota of its own, so any file it *creates* fails with
    "storageQuotaExceeded" — even inside your folder. The workaround for a
    personal Google account is: YOU create the six empty Docs by hand and share
    each with the service account as Editor. This function then just finds and
    updates them (updating a file you own doesn't touch the robot's quota).

    Raises FileNotFoundError if the Doc doesn't exist yet, so the caller can
    print a helpful message telling you which Doc to create.
    """
    # Search for the existing Doc with this exact name in the folder.
    q = (
        f"name = '{title.replace(chr(39), chr(92) + chr(39))}' "
        f"and '{folder_id}' in parents "
        "and mimeType = 'application/vnd.google-apps.document' "
        "and trashed = false"
    )
    resp = drive.files().list(
        q=q, spaces="drive", fields="files(id, name)",
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    files = resp.get("files", [])
    if files:
        return files[0]["id"]

    raise FileNotFoundError(
        f"No Doc named '{title}' found in the folder. Create an empty Google "
        f"Doc with exactly that name and share it with the service account "
        f"(Editor), then re-run."
    )


def replace_doc_text(docs, doc_id: str, text: str) -> None:
    """Replace the entire body of a Google Doc with `text`."""
    # Read the current end index so we can delete existing content.
    doc = docs.documents().get(documentId=doc_id).execute()
    content = doc.get("body", {}).get("content", [])
    end_index = 1
    for element in content:
        if "endIndex" in element:
            end_index = max(end_index, element["endIndex"])

    requests = []
    # Delete existing body (range 1..end-1); skip if the doc is essentially empty.
    if end_index > 2:
        requests.append({
            "deleteContentRange": {
                "range": {"startIndex": 1, "endIndex": end_index - 1}
            }
        })
    # Insert the new text at the top.
    requests.append({
        "insertText": {"location": {"index": 1}, "text": text}
    })
    docs.documents().batchUpdate(
        documentId=doc_id, body={"requests": requests}
    ).execute()


if __name__ == "__main__":
    sys.exit(main())
