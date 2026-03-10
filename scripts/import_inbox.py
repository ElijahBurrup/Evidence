"""
Import evidence from the local evidence_inbox/ folder into the database.
Handles BestInterest app exports (CSV messages, CSV journals, JSON+audio call recordings).
Uses Claude AI to analyze content and auto-categorize, extract quotes, rate severity.

Usage: cd C:/Projects/Evidence && python scripts/import_inbox.py
"""

import os
import sys
import re
import csv
import json
import shutil
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app, db, EvidenceItem, EVIDENCE_CATEGORIES

INBOX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evidence_inbox")
CATEGORY_KEYS = list(EVIDENCE_CATEGORIES.keys())

# ---------------------------------------------------------------------------
# Claude AI Analysis
# ---------------------------------------------------------------------------
ANALYSIS_PROMPT = """You are a family law evidence analyst. You are reviewing evidence in a custody case.

CONTEXT:
- Elijah ("Eli") is the father seeking full custody of his 14-year-old daughter Kyra.
- Melissa is the mother / opposing party.
- Kyra is mature and has expressed a clear desire to live with her father.
- We are documenting patterns of behavior by Melissa that support the child's preference and Elijah's petition.
- We must NOT fabricate, exaggerate, or manipulate anything. Only document what the evidence actually shows.
- If evidence is neutral, mundane, or shows cooperation, label it honestly as such.

WHAT TO LOOK FOR:
- Parental alienation (turning Kyra against Eli, coaching, guilt for enjoying time with dad)
- False accusations (unfounded claims about Eli)
- Verbal abuse / yelling / name-calling (hostile language, raised voice, demeaning)
- Withholding (medical info, school info, access, belongings)
- Gatekeeping (unilateral decisions, controlling access)
- Communication interference (ignoring, blocking, refusing to cooperate)
- Schedule violations (late, cancelled, refused exchanges)
- Emotional manipulation (guilt trips, using child as messenger, loyalty conflicts)
- Impact on child (Kyra's distress, coached statements, behavioral changes)
- Cooperation attempts by Eli (reasonable communication, following the plan)

Analyze the evidence and respond with ONLY a JSON object. No markdown, no backticks.

{
  "title": "Short descriptive title, max 80 chars. Include WHO did WHAT.",
  "category": "primary category key from list below",
  "subcategories": ["additional applicable category keys"],
  "severity": 1 to 5 integer,
  "child_present": true/false,
  "key_quotes": ["EXACT quotes from the text, max 5, most relevant to custody case"],
  "description": "2-3 sentence factual summary of what this evidence shows and why it matters. Be precise, not emotional.",
  "tags": ["keyword tags, max 6"],
  "people_present": "names of people mentioned or involved",
  "is_significant": true/false (false if mundane logistics with no evidentiary value)
}

VALID CATEGORY KEYS:
parental_alienation, false_accusations, communication_interference, verbal_abuse,
withholding, gatekeeping, schedule_violations, emotional_manipulation,
documentation_of_cooperation, impact_on_child, financial_abuse, third_party_witness

SEVERITY GUIDE:
5 = safety threat, child endangered, severe verbal abuse in front of child
4 = clear order violation, sustained hostile behavior, direct alienation statements
3 = significant incident with evidentiary value
2 = noteworthy pattern piece, mild on its own
1 = background context, routine logistics

IMPORTANT:
- key_quotes must be EXACT text from the evidence, never paraphrased
- If this is just routine co-parenting logistics (scheduling, thumbs up, etc.), mark is_significant=false, severity=1, category=documentation_of_cooperation
- Be honest. If Eli is being reasonable, that IS evidence (of cooperation). Label it correctly.

EVIDENCE TYPE: {evidence_type}
DATE: {event_date}

CONTENT:
{content}"""


def get_anthropic_client():
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        env_path = "C:/Projects/KingdomBuilders.AI/SunoSmart/.env"
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith("ANTHROPIC_API_KEY="):
                        api_key = line.split("=", 1)[1].strip()
                        break
    if not api_key:
        print("ERROR: No ANTHROPIC_API_KEY found.")
        sys.exit(1)
    return anthropic.Anthropic(api_key=api_key)


def analyze_with_claude(client, content, evidence_type, event_date):
    date_str = event_date.strftime("%Y-%m-%d %I:%M %p") if event_date else "Unknown"
    prompt = ANALYSIS_PROMPT.replace("{evidence_type}", evidence_type).replace("{event_date}", date_str).replace("{content}", content[:10000])
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        analysis = json.loads(raw)
        if analysis.get("category") not in CATEGORY_KEYS:
            analysis["category"] = "verbal_abuse"
        analysis["subcategories"] = [s for s in analysis.get("subcategories", []) if s in CATEGORY_KEYS]
        analysis["severity"] = max(1, min(5, int(analysis.get("severity", 3))))
        return analysis
    except Exception as e:
        print(f"    AI analysis failed: {e}")
        return None


def transcribe_audio(filepath):
    try:
        from faster_whisper import WhisperModel
        print(f"    Transcribing audio...")
        model = WhisperModel("base", device="cpu")
        segments, info = model.transcribe(filepath)
        lines = []
        for seg in segments:
            m = int(seg.start // 60)
            s = int(seg.start % 60)
            lines.append(f"[{m:02d}:{s:02d}] {seg.text.strip()}")
        print(f"    Transcribed: {len(lines)} segments")
        return "\n".join(lines)
    except ImportError:
        print("    WARNING: faster-whisper not installed, skipping transcription")
        print("    Install with: pip install faster-whisper")
        return None
    except Exception as e:
        print(f"    Transcription error: {e}")
        return None


# ---------------------------------------------------------------------------
# CSV Message Import — BestInterest format
# ---------------------------------------------------------------------------
def import_messages_csv(csv_path, client):
    """Import BestInterest message CSV. Groups messages into conversation windows."""
    print(f"\n{'='*60}")
    print(f"  IMPORTING TEXT MESSAGES")
    print(f"  Source: {os.path.basename(csv_path)}")
    print(f"{'='*60}")

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        messages = list(reader)

    print(f"  Total messages: {len(messages)}")

    # Group messages into conversation windows (same day, with gaps < 2 hours)
    windows = []
    current_window = []

    for msg in messages:
        if not msg.get("Date") or not msg.get("Message"):
            continue
        try:
            dt = datetime.fromisoformat(msg["Date"].replace("Z", "+00:00")).replace(tzinfo=None)
        except (ValueError, TypeError):
            continue

        msg["_dt"] = dt

        if current_window:
            last_dt = current_window[-1]["_dt"]
            gap = (dt - last_dt).total_seconds()
            # New window if gap > 2 hours
            if gap > 7200:
                windows.append(current_window)
                current_window = [msg]
            else:
                current_window.append(msg)
        else:
            current_window.append(msg)

    if current_window:
        windows.append(current_window)

    print(f"  Conversation windows: {len(windows)}")

    imported = 0
    skipped_mundane = 0

    for i, window in enumerate(windows):
        first_dt = window[0]["_dt"]
        last_dt = window[-1]["_dt"]

        # Build conversation text
        lines = []
        for msg in window:
            timestamp = msg["_dt"].strftime("%I:%M %p")
            sender = msg.get("From", "Unknown")
            text = msg.get("Message", "").strip()
            direction = msg.get("Direction", "")
            flagged = msg.get("User Flagged", "No")
            flag_mark = " [FLAGGED]" if flagged == "Yes" else ""
            if text:
                lines.append(f"[{timestamp}] {sender}: {text}{flag_mark}")

        conversation_text = "\n".join(lines)
        if not conversation_text.strip():
            continue

        # Check for duplicates by date range
        existing = EvidenceItem.query.filter(
            EvidenceItem.evidence_type == "text_message",
            EvidenceItem.event_date == first_dt,
        ).first()
        if existing:
            skipped_mundane += 1
            continue

        # AI Analysis
        print(f"\n  Window {i+1}/{len(windows)}: {first_dt.strftime('%b %d %Y %I:%M %p')} ({len(window)} msgs)")
        analysis = analyze_with_claude(client, conversation_text, "text_message_thread", first_dt)

        if not analysis:
            continue

        # Skip mundane logistics unless flagged
        has_flagged = any(m.get("User Flagged") == "Yes" for m in window)
        if analysis.get("is_significant") is False and not has_flagged:
            print(f"    MUNDANE (skipping): {analysis.get('title', 'untitled')}")
            skipped_mundane += 1
            continue

        title = analysis.get("title", f"Text conversation {first_dt.strftime('%m/%d/%Y')}")
        print(f"    → {analysis['category']}, sev={analysis['severity']}: {title}")

        item = EvidenceItem(
            title=title,
            description=analysis.get("description"),
            evidence_type="text_message",
            category=analysis["category"],
            subcategories=json.dumps(analysis.get("subcategories", [])) or None,
            event_date=first_dt,
            raw_text=conversation_text,
            key_quotes=json.dumps(analysis.get("key_quotes", [])) or None,
            severity=analysis["severity"],
            people_present=analysis.get("people_present"),
            child_present=analysis.get("child_present", False),
            tags=json.dumps(analysis.get("tags", [])) or None,
        )
        db.session.add(item)
        imported += 1

        # Commit every 10 to avoid losing work
        if imported % 10 == 0:
            db.session.commit()

    db.session.commit()
    print(f"\n  Messages: Imported {imported}, Skipped mundane {skipped_mundane}")
    return imported


# ---------------------------------------------------------------------------
# CSV Journal Import — BestInterest format
# ---------------------------------------------------------------------------
def import_journals_csv(csv_path, client):
    """Import BestInterest journal entries CSV."""
    print(f"\n{'='*60}")
    print(f"  IMPORTING JOURNAL ENTRIES")
    print(f"  Source: {os.path.basename(csv_path)}")
    print(f"{'='*60}")

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    # BestInterest journal CSV has a 3-line header before the actual data
    lines = content.split("\n")
    # Find the actual header row (starts with "Date")
    data_start = 0
    for i, line in enumerate(lines):
        if line.strip().startswith('"Date"'):
            data_start = i
            break

    csv_text = "\n".join(lines[data_start:])
    reader = csv.DictReader(csv_text.splitlines())
    entries = list(reader)

    print(f"  Total journal entries: {len(entries)}")

    imported = 0

    for i, entry in enumerate(entries):
        note = entry.get("Note", "").strip()
        date_str = entry.get("Date", "")

        if not note or not date_str:
            continue

        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00")).replace(tzinfo=None)
        except (ValueError, TypeError):
            continue

        # Check for duplicate
        existing = EvidenceItem.query.filter(
            EvidenceItem.evidence_type == "journal",
            EvidenceItem.event_date == dt,
        ).first()
        if existing:
            continue

        print(f"\n  Entry {i+1}/{len(entries)}: {dt.strftime('%b %d %Y')}")

        analysis = analyze_with_claude(client, note, "journal_entry", dt)

        if analysis:
            title = analysis.get("title", f"Journal entry {dt.strftime('%m/%d/%Y')}")
            print(f"    → {analysis['category']}, sev={analysis['severity']}: {title}")
        else:
            title = f"Journal entry {dt.strftime('%m/%d/%Y')}"
            analysis = {"category": "impact_on_child", "severity": 3, "subcategories": [],
                        "key_quotes": [], "tags": [], "child_present": False}

        item = EvidenceItem(
            title=title,
            description=analysis.get("description"),
            evidence_type="journal",
            category=analysis["category"],
            subcategories=json.dumps(analysis.get("subcategories", [])) or None,
            event_date=dt,
            raw_text=note,
            key_quotes=json.dumps(analysis.get("key_quotes", [])) or None,
            severity=analysis["severity"],
            people_present=analysis.get("people_present"),
            child_present=analysis.get("child_present", False),
            tags=json.dumps(analysis.get("tags", [])) or None,
        )
        db.session.add(item)
        imported += 1

        if imported % 5 == 0:
            db.session.commit()

    db.session.commit()
    print(f"\n  Journals: Imported {imported}")
    return imported


# ---------------------------------------------------------------------------
# Audio Import — JSON metadata + AMR/M4A files
# ---------------------------------------------------------------------------
def import_audio_files(audio_dir, client):
    """Import audio call recordings with JSON metadata."""
    print(f"\n{'='*60}")
    print(f"  IMPORTING AUDIO RECORDINGS")
    print(f"{'='*60}")

    # Find all JSON metadata files
    json_files = sorted([f for f in os.listdir(audio_dir) if f.endswith(".json")])
    print(f"  Total recordings: {len(json_files)}")

    imported = 0
    uploads_dir = os.path.join(os.path.dirname(INBOX), "uploads", "audio")
    os.makedirs(uploads_dir, exist_ok=True)
    transcripts_dir = os.path.join(os.path.dirname(INBOX), "transcripts")
    os.makedirs(transcripts_dir, exist_ok=True)

    for json_file in json_files:
        json_path = os.path.join(audio_dir, json_file)

        # Find the matching audio file (same name, different ext)
        base = json_file.rsplit(".", 1)[0]
        audio_file = None
        for ext in [".m4a", ".amr", ".mp3", ".wav", ".ogg", ".aac"]:
            candidate = base + ext
            if os.path.exists(os.path.join(audio_dir, candidate)):
                audio_file = candidate
                break

        if not audio_file:
            continue

        audio_path = os.path.join(audio_dir, audio_file)

        # Parse date from filename: "2025-05-30 13-23-13 (phone) ..."
        m = re.match(r"(\d{4}-\d{2}-\d{2}) (\d{2}-\d{2}-\d{2})", json_file)
        if m:
            dt = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H-%M-%S")
        else:
            dt = datetime.fromtimestamp(os.path.getmtime(audio_path))

        # Check for duplicate
        existing = EvidenceItem.query.filter(
            EvidenceItem.evidence_type.in_(["audio", "voicemail"]),
            EvidenceItem.event_date == dt,
        ).first()
        if existing:
            print(f"  SKIP (exists): {audio_file[:60]}")
            continue

        # Read JSON metadata
        with open(json_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        duration_ms = int(meta.get("duration", 0))
        duration_min = duration_ms / 60000
        direction = meta.get("direction", "Unknown")
        starred = meta.get("starred", "false") == "true"

        # Parse caller info from filename
        caller_info = base
        # Extract name: "... (phone) Melissa ((918) 697-8371) ↙"
        name_match = re.search(r"\(phone\)\s+(.+?)(?:\s*\([\(\)0-9\-\s]+\))?\s*[↙↗]?$", base)
        caller_name = name_match.group(1).strip() if name_match else "Unknown"

        evidence_type = "voicemail" if duration_min < 1 else "audio"

        print(f"\n  {audio_file[:70]}")
        print(f"    Duration: {duration_min:.1f} min | Direction: {direction} | Starred: {starred}")

        # Copy audio to uploads
        safe_filename = re.sub(r'[<>:"/\\|?*↙↗]', '_', audio_file)
        dest = os.path.join(uploads_dir, safe_filename)
        shutil.copy2(audio_path, dest)
        file_path_db = f"uploads/audio/{safe_filename}"

        # Transcribe
        transcript = transcribe_audio(audio_path)

        # AI analysis on transcript or metadata
        analysis = None
        analyzable = transcript or f"Phone call with {caller_name}. Direction: {direction}. Duration: {duration_min:.1f} minutes. Starred: {starred}."
        if transcript or starred:
            analysis = analyze_with_claude(client, analyzable, f"phone_call_{direction.lower()}", dt)

        if analysis:
            title = analysis.get("title", f"Call with {caller_name}")
            print(f"    → {analysis['category']}, sev={analysis['severity']}: {title}")
        else:
            direction_label = "from" if direction == "Incoming" else "to"
            title = f"Phone call {direction_label} {caller_name} ({duration_min:.0f} min)"
            analysis = {
                "category": "communication_interference" if not transcript else "verbal_abuse",
                "severity": 2 if starred else 1,
                "subcategories": [],
                "key_quotes": [],
                "tags": [caller_name.lower(), "phone call", direction.lower()],
                "child_present": False,
                "people_present": f"Eli, {caller_name}",
                "description": f"Phone call {direction_label} {caller_name}, {duration_min:.1f} minutes.",
            }

        # Save transcript to file
        if transcript:
            safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)[:80]
            t_path = os.path.join(transcripts_dir, f"{dt.strftime('%Y-%m-%d_%H%M')}_{safe_title}.txt")
            with open(t_path, "w", encoding="utf-8") as f:
                f.write(f"TRANSCRIPT: {title}\n")
                f.write(f"Date: {dt.strftime('%Y-%m-%d %I:%M %p')}\n")
                f.write(f"Direction: {direction} | Duration: {duration_min:.1f} min\n")
                f.write(f"Category: {EVIDENCE_CATEGORIES.get(analysis['category'], {}).get('label', '')}\n")
                f.write(f"{'='*60}\n\n")
                f.write(transcript)

        item = EvidenceItem(
            title=title,
            description=analysis.get("description"),
            evidence_type=evidence_type,
            category=analysis["category"],
            subcategories=json.dumps(analysis.get("subcategories", [])) or None,
            event_date=dt,
            file_path=file_path_db,
            transcript=transcript,
            key_quotes=json.dumps(analysis.get("key_quotes", [])) or None,
            severity=analysis["severity"],
            people_present=analysis.get("people_present"),
            child_present=analysis.get("child_present", False),
            tags=json.dumps(analysis.get("tags", [])) or None,
        )
        db.session.add(item)
        imported += 1

        if imported % 5 == 0:
            db.session.commit()

    db.session.commit()
    print(f"\n  Audio: Imported {imported}")
    return imported


# ---------------------------------------------------------------------------
# Screenshot Import
# ---------------------------------------------------------------------------
def import_screenshots(screenshot_dir, client):
    """Import screenshot evidence files."""
    print(f"\n{'='*60}")
    print(f"  IMPORTING SCREENSHOTS")
    print(f"{'='*60}")

    imported = 0
    uploads_dir = os.path.join(os.path.dirname(INBOX), "uploads", "screenshots")
    os.makedirs(uploads_dir, exist_ok=True)

    # Check root and Archive subdirectory
    for subdir in ["", "Archive"]:
        scan_dir = os.path.join(screenshot_dir, subdir) if subdir else screenshot_dir
        if not os.path.isdir(scan_dir):
            continue

        for filename in sorted(os.listdir(scan_dir)):
            if not filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                continue

            filepath = os.path.join(scan_dir, filename)

            # Parse date from filename: 20240213_153826
            m = re.match(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", filename)
            if m:
                dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                              int(m.group(4)), int(m.group(5)), int(m.group(6)))
            else:
                dt = datetime.fromtimestamp(os.path.getmtime(filepath))

            # Check duplicate
            existing = EvidenceItem.query.filter(
                EvidenceItem.evidence_type == "screenshot",
                EvidenceItem.event_date == dt,
            ).first()
            if existing:
                continue

            safe_filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
            dest = os.path.join(uploads_dir, safe_filename)
            shutil.copy2(filepath, dest)

            title = f"Screenshot {dt.strftime('%m/%d/%Y %I:%M %p')}"
            print(f"  Imported: {filename}")

            item = EvidenceItem(
                title=title,
                evidence_type="screenshot",
                category="documentation_of_cooperation",
                event_date=dt,
                file_path=f"uploads/screenshots/{safe_filename}",
                severity=2,
                description="Screenshot evidence. Review and recategorize manually.",
            )
            db.session.add(item)
            imported += 1

    db.session.commit()
    print(f"  Screenshots: Imported {imported}")
    return imported


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    app = create_app()

    print("Initializing Claude AI for evidence analysis...")
    client = get_anthropic_client()
    print("Claude AI ready.\n")

    total_imported = 0

    with app.app_context():
        # 1. Import text messages CSV
        texts_dir = os.path.join(INBOX, "texts")
        for f in os.listdir(texts_dir) if os.path.isdir(texts_dir) else []:
            if f.endswith(".csv"):
                total_imported += import_messages_csv(os.path.join(texts_dir, f), client)

        # 2. Import journal entries CSV
        journals_dir = os.path.join(INBOX, "journals")
        for f in os.listdir(journals_dir) if os.path.isdir(journals_dir) else []:
            if f.endswith(".csv"):
                total_imported += import_journals_csv(os.path.join(journals_dir, f), client)

        # 3. Import audio recordings
        audio_dir = os.path.join(INBOX, "audio")
        if os.path.isdir(audio_dir):
            total_imported += import_audio_files(audio_dir, client)

        # 4. Import screenshots
        screenshots_dir = os.path.join(INBOX, "screenshots")
        if os.path.isdir(screenshots_dir):
            total_imported += import_screenshots(screenshots_dir, client)

    print(f"\n{'='*60}")
    print(f"  IMPORT COMPLETE: {total_imported} evidence items imported")
    print(f"  View at: http://localhost:5050/timeline")
    print(f"  Dashboard: http://localhost:5050/dashboard")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
