"""
Batch transcribe all audio evidence.
Step 1: Convert all audio files to WAV (fast, ffmpeg)
Step 2: Transcribe all WAVs with whisper (one model load)
Step 3: Re-analyze with Claude AI

Usage: cd C:/Projects/Evidence && python -u scripts/batch_transcribe.py
"""

import os
import sys
import re
import json
import subprocess
import signal
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app, db, EvidenceItem, EVIDENCE_CATEGORIES

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INBOX = os.path.join(PROJECT_ROOT, "evidence_inbox")
WAV_DIR = os.path.join(PROJECT_ROOT, "temp_wavs")
TRANSCRIPTS_DIR = os.path.join(PROJECT_ROOT, "transcripts")
CATEGORY_KEYS = list(EVIDENCE_CATEGORIES.keys())

ANALYSIS_PROMPT = """You are a family law evidence analyst reviewing a phone call transcript in a custody case.

CONTEXT:
- Elijah ("Eli") is the father seeking full custody of his 14-year-old daughter Kyra.
- Melissa is the mother / opposing party.
- Kelly Smakel is Melissa's attorney.
- Alice is a therapist.
- We must NOT fabricate or exaggerate. Only document what the transcript shows.

Analyze and respond with ONLY a JSON object (no markdown, no backticks):

{
  "title": "Short descriptive title, max 80 chars, WHO did WHAT",
  "category": "primary category key",
  "subcategories": ["additional category keys"],
  "severity": 1-5 integer,
  "child_present": true/false,
  "key_quotes": ["EXACT quotes from transcript, max 5"],
  "description": "2-3 sentence factual summary",
  "tags": ["keyword tags, max 6"],
  "people_present": "people heard or present"
}

CATEGORIES: parental_alienation, false_accusations, communication_interference, verbal_abuse, withholding, gatekeeping, schedule_violations, emotional_manipulation, documentation_of_cooperation, impact_on_child, financial_abuse, third_party_witness

SEVERITY: 5=safety, 4=clear violation/alienation, 3=significant, 2=noteworthy, 1=routine

Direction: DIRECTION_VAL | Duration: DURATION_VAL min | Other party: CALLER_VAL | Date: DATE_VAL

TRANSCRIPT:
TRANSCRIPT_VAL"""


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
        print("ERROR: No ANTHROPIC_API_KEY found.", flush=True)
        sys.exit(1)
    return anthropic.Anthropic(api_key=api_key)


def analyze_with_claude(client, transcript, direction, duration, caller, date):
    date_str = date.strftime("%Y-%m-%d %I:%M %p") if date else "Unknown"
    prompt = (ANALYSIS_PROMPT
              .replace("TRANSCRIPT_VAL", transcript[:12000])
              .replace("DIRECTION_VAL", direction)
              .replace("DURATION_VAL", f"{duration:.1f}")
              .replace("CALLER_VAL", caller)
              .replace("DATE_VAL", date_str))
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
        print(f"    AI error: {e}", flush=True)
        return None


def main():
    app = create_app()
    os.makedirs(WAV_DIR, exist_ok=True)
    os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)

    with app.app_context():
        # Find items needing transcription
        items = EvidenceItem.query.filter(
            EvidenceItem.evidence_type.in_(["audio", "voicemail"]),
            EvidenceItem.transcript.is_(None),
        ).order_by(EvidenceItem.event_date).all()

        print(f"Found {len(items)} audio items needing transcription.\n", flush=True)
        if not items:
            print("Nothing to do!", flush=True)
            return

        # ---------------------------------------------------------------
        # STEP 1: Convert all audio to WAV
        # ---------------------------------------------------------------
        print("=" * 60, flush=True)
        print("  STEP 1: Converting audio to WAV", flush=True)
        print("=" * 60, flush=True)

        wav_map = {}  # item.id -> wav_path
        for i, item in enumerate(items):
            # Find source file
            source = None
            if item.file_path:
                uploaded = os.path.join(PROJECT_ROOT, item.file_path)
                if os.path.exists(uploaded):
                    source = uploaded
            if not source:
                dt = item.event_date
                date_prefix = dt.strftime("%Y-%m-%d %H-%M-%S")
                audio_dir = os.path.join(INBOX, "audio")
                if os.path.isdir(audio_dir):
                    for f in os.listdir(audio_dir):
                        if f.startswith(date_prefix) and not f.endswith(".json"):
                            source = os.path.join(audio_dir, f)
                            break

            if not source:
                print(f"  [{i+1}/{len(items)}] SKIP (no source): {item.title[:60]}", flush=True)
                continue

            wav_path = os.path.join(WAV_DIR, f"{item.id}.wav")
            if os.path.exists(wav_path) and os.path.getsize(wav_path) > 0:
                wav_map[item.id] = wav_path
                print(f"  [{i+1}/{len(items)}] EXISTS: {os.path.basename(source)[:50]}", flush=True)
                continue

            try:
                r = subprocess.run(
                    ["ffmpeg", "-y", "-i", source, "-ar", "16000", "-ac", "1", wav_path],
                    capture_output=True, timeout=120
                )
                if r.returncode == 0 and os.path.exists(wav_path) and os.path.getsize(wav_path) > 0:
                    size_kb = os.path.getsize(wav_path) / 1024
                    wav_map[item.id] = wav_path
                    print(f"  [{i+1}/{len(items)}] OK ({size_kb:.0f}KB): {os.path.basename(source)[:50]}", flush=True)
                else:
                    print(f"  [{i+1}/{len(items)}] FAIL: {os.path.basename(source)[:50]}", flush=True)
                    if r.stderr:
                        print(f"    {r.stderr.decode()[:100]}", flush=True)
            except subprocess.TimeoutExpired:
                print(f"  [{i+1}/{len(items)}] TIMEOUT: {os.path.basename(source)[:50]}", flush=True)
            except Exception as e:
                print(f"  [{i+1}/{len(items)}] ERROR: {e}", flush=True)

        print(f"\n  Converted {len(wav_map)} of {len(items)} files.\n", flush=True)

        # ---------------------------------------------------------------
        # STEP 2: Transcribe all WAVs
        # ---------------------------------------------------------------
        print("=" * 60, flush=True)
        print("  STEP 2: Transcribing with Whisper", flush=True)
        print("=" * 60, flush=True)

        from faster_whisper import WhisperModel
        print("  Loading model...", flush=True)
        model = WhisperModel("base", device="cpu", compute_type="int8")
        print("  Model loaded.\n", flush=True)

        transcribed = 0
        failed = 0
        transcript_map = {}  # item.id -> transcript text

        for item_id, wav_path in wav_map.items():
            item = EvidenceItem.query.get(item_id)
            if item.transcript:
                continue

            size_mb = os.path.getsize(wav_path) / (1024 * 1024)
            print(f"  [{transcribed+failed+1}/{len(wav_map)}] {item.event_date.strftime('%m/%d/%Y')} ({size_mb:.1f}MB)...", end="", flush=True)

            try:
                segments, info = model.transcribe(wav_path, language="en")
                lines = []
                for seg in segments:
                    m = int(seg.start // 60)
                    s = int(seg.start % 60)
                    text = seg.text.strip()
                    if text:
                        lines.append(f"[{m:02d}:{s:02d}] {text}")
                transcript = "\n".join(lines)

                if transcript and len(transcript) > 10:
                    transcript_map[item_id] = transcript
                    item.transcript = transcript
                    db.session.commit()
                    transcribed += 1
                    print(f" {len(lines)} segments, {len(transcript.split())} words", flush=True)
                else:
                    failed += 1
                    print(f" empty transcript", flush=True)
            except Exception as e:
                failed += 1
                print(f" ERROR: {e}", flush=True)

        print(f"\n  Transcribed: {transcribed}, Failed: {failed}\n", flush=True)

        # ---------------------------------------------------------------
        # STEP 3: AI Analysis
        # ---------------------------------------------------------------
        print("=" * 60, flush=True)
        print("  STEP 3: AI Analysis with Claude", flush=True)
        print("=" * 60, flush=True)

        client = get_anthropic_client()
        analyzed = 0

        for item_id, transcript in transcript_map.items():
            item = EvidenceItem.query.get(item_id)

            # Get call metadata
            dt = item.event_date
            date_prefix = dt.strftime("%Y-%m-%d %H-%M-%S")
            direction = "Unknown"
            duration_min = 0
            audio_dir = os.path.join(INBOX, "audio")
            if os.path.isdir(audio_dir):
                for jf in os.listdir(audio_dir):
                    if jf.startswith(date_prefix) and jf.endswith(".json"):
                        with open(os.path.join(audio_dir, jf)) as f:
                            meta = json.load(f)
                        direction = meta.get("direction", "Unknown")
                        duration_min = int(meta.get("duration", 0)) / 60000
                        break

            # Parse caller
            caller = "Unknown"
            title = item.title or ""
            if "Kelly Smakel" in title:
                caller = "Kelly Smakel (Melissa's Attorney)"
            elif "Alice" in title and "Therapist" in title:
                caller = "Alice (Therapist)"
            elif "Melissa" in title:
                caller = "Melissa"

            print(f"  [{analyzed+1}] {dt.strftime('%m/%d/%Y')} {caller}...", end="", flush=True)
            analysis = analyze_with_claude(client, transcript, direction, duration_min, caller, dt)

            if analysis:
                item.title = analysis.get("title", item.title)
                item.category = analysis["category"]
                item.subcategories = json.dumps(analysis.get("subcategories", [])) or None
                item.severity = analysis["severity"]
                cp = analysis.get("child_present", False)
                item.child_present = cp is True or cp == "true"
                item.key_quotes = json.dumps(analysis.get("key_quotes", [])) or None
                item.description = analysis.get("description")
                item.people_present = analysis.get("people_present")
                item.tags = json.dumps(analysis.get("tags", [])) or None

                cat = EVIDENCE_CATEGORIES.get(item.category, {}).get("label", item.category)
                print(f" {cat}, sev={item.severity}", flush=True)

                # Save transcript file
                safe = re.sub(r'[<>:"/\\|?*]', '_', item.title)[:80]
                t_path = os.path.join(TRANSCRIPTS_DIR, f"{dt.strftime('%Y-%m-%d_%H%M')}_{safe}.txt")
                with open(t_path, "w", encoding="utf-8") as f:
                    f.write(f"TRANSCRIPT: {item.title}\n")
                    f.write(f"Date: {dt.strftime('%Y-%m-%d %I:%M %p')}\n")
                    f.write(f"Direction: {direction} | Duration: {duration_min:.1f} min\n")
                    f.write(f"Category: {cat}\n")
                    f.write(f"Severity: {item.severity}/5\n")
                    f.write(f"{'='*60}\n\n")
                    f.write(transcript)
            else:
                print(f" AI failed", flush=True)

            db.session.commit()
            analyzed += 1

        # Cleanup temp WAVs
        import shutil
        shutil.rmtree(WAV_DIR, ignore_errors=True)

        print(f"\n{'='*60}", flush=True)
        print(f"  COMPLETE", flush=True)
        print(f"  Transcribed: {transcribed}", flush=True)
        print(f"  Analyzed: {analyzed}", flush=True)
        total_done = EvidenceItem.query.filter(EvidenceItem.evidence_type.in_(['audio','voicemail'])).filter(EvidenceItem.transcript.isnot(None)).count()
        total_all = EvidenceItem.query.filter(EvidenceItem.evidence_type.in_(['audio','voicemail'])).count()
        print(f"  Total with transcripts: {total_done}/{total_all}", flush=True)
        print(f"{'='*60}", flush=True)


if __name__ == "__main__":
    main()
