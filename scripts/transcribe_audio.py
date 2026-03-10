"""
Transcribe all audio evidence items that don't have transcripts yet.
Re-analyzes with Claude AI after transcription for proper categorization.

Usage: cd C:/Projects/Evidence && python scripts/transcribe_audio.py
"""

import os
import sys
import re
import json
import subprocess
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app, db, EvidenceItem, EVIDENCE_CATEGORIES

INBOX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evidence_inbox")
CATEGORY_KEYS = list(EVIDENCE_CATEGORIES.keys())

ANALYSIS_PROMPT = """You are a family law evidence analyst. You are reviewing a phone call transcript in a custody case.

CONTEXT:
- Elijah ("Eli") is the father seeking full custody of his 14-year-old daughter Kyra.
- Melissa is the mother / opposing party.
- Kelly Smakel is Melissa's attorney.
- Alice is a therapist.
- Kyra is mature and has expressed a clear desire to live with her father.
- We must NOT fabricate, exaggerate, or manipulate anything. Only document what the transcript actually shows.
- If the call is neutral or cooperative, label it honestly.

WHAT TO LOOK FOR:
- Parental alienation (turning Kyra against Eli, coaching, guilt)
- False accusations (unfounded claims about Eli)
- Verbal abuse / yelling / name-calling (hostile language, demeaning)
- Withholding (medical info, school info, access, belongings)
- Gatekeeping (unilateral decisions, controlling access)
- Communication interference (ignoring, blocking, refusing to cooperate)
- Schedule violations (late, cancelled, refused exchanges)
- Emotional manipulation (guilt trips, using child as messenger)
- Impact on child (Kyra's distress, coached statements)
- Cooperation by Eli (reasonable, following the plan)

Analyze the transcript and respond with ONLY a JSON object. No markdown, no backticks.

{
  "title": "Short descriptive title, max 80 chars. Include WHO did WHAT.",
  "category": "primary category key",
  "subcategories": ["additional category keys"],
  "severity": 1-5 integer,
  "child_present": true/false (was Kyra audibly present or discussed as being in the room),
  "key_quotes": ["EXACT quotes from transcript, max 5, most relevant"],
  "description": "2-3 sentence factual summary. Be precise, not emotional.",
  "tags": ["keyword tags, max 6"],
  "people_present": "people heard or referenced as present"
}

VALID CATEGORIES:
parental_alienation, false_accusations, communication_interference, verbal_abuse,
withholding, gatekeeping, schedule_violations, emotional_manipulation,
documentation_of_cooperation, impact_on_child, financial_abuse, third_party_witness

SEVERITY: 5=safety/child endangered, 4=clear violation/sustained hostility/alienation,
3=significant, 2=noteworthy, 1=routine/background

CALL INFO:
Direction: {direction}
Duration: {duration} minutes
Other party: {caller}
Date: {date}

TRANSCRIPT:
{transcript}"""


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


def analyze_with_claude(client, transcript, direction, duration, caller, date):
    date_str = date.strftime("%Y-%m-%d %I:%M %p") if date else "Unknown"
    prompt = (ANALYSIS_PROMPT
              .replace("{transcript}", transcript[:12000])
              .replace("{direction}", direction)
              .replace("{duration}", f"{duration:.1f}")
              .replace("{caller}", caller)
              .replace("{date}", date_str))
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


def convert_amr_to_wav(amr_path):
    """Convert AMR to WAV using ffmpeg for whisper compatibility."""
    wav_path = tempfile.mktemp(suffix=".wav")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", amr_path, "-ar", "16000", "-ac", "1", wav_path],
            capture_output=True, timeout=60
        )
        if os.path.exists(wav_path) and os.path.getsize(wav_path) > 0:
            return wav_path
    except Exception as e:
        print(f"    FFmpeg conversion failed: {e}")
    return None


_whisper_model = None

def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        print("  Loading whisper model...", flush=True)
        _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
    return _whisper_model


def transcribe_file(filepath):
    """Transcribe an audio file using faster-whisper."""
    ext = os.path.splitext(filepath)[1].lower()
    temp_wav = None

    # Convert AMR to WAV first
    if ext == ".amr":
        print("    Converting AMR to WAV...", flush=True)
        temp_wav = convert_amr_to_wav(filepath)
        if not temp_wav:
            print("    AMR conversion failed", flush=True)
            return None
        filepath = temp_wav

    # Convert M4A to WAV for reliability
    if ext == ".m4a":
        print("    Converting M4A to WAV...", flush=True)
        temp_wav = tempfile.mktemp(suffix=".wav")
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", filepath, "-ar", "16000", "-ac", "1", temp_wav],
                capture_output=True, timeout=120
            )
            if os.path.exists(temp_wav) and os.path.getsize(temp_wav) > 0:
                filepath = temp_wav
            else:
                temp_wav = None
        except Exception as e:
            print(f"    M4A conversion failed: {e}", flush=True)
            temp_wav = None

    try:
        model = get_whisper_model()
        segments, info = model.transcribe(filepath, language="en")
        lines = []
        for seg in segments:
            m = int(seg.start // 60)
            s = int(seg.start % 60)
            text = seg.text.strip()
            if text:
                lines.append(f"[{m:02d}:{s:02d}] {text}")
        return "\n".join(lines)
    except Exception as e:
        print(f"    Transcription error: {e}", flush=True)
        return None
    finally:
        if temp_wav and os.path.exists(temp_wav):
            os.remove(temp_wav)


def find_source_audio(item):
    """Find the audio file — check uploads copy first, then inbox original."""
    project_root = os.path.dirname(INBOX)

    # 1. Check uploaded copy (already in uploads/audio/)
    if item.file_path:
        uploaded = os.path.join(project_root, item.file_path)
        if os.path.exists(uploaded) and os.path.getsize(uploaded) > 0:
            return uploaded

    # 2. Check inbox by date prefix
    audio_dir = os.path.join(INBOX, "audio")
    if not os.path.isdir(audio_dir):
        return None

    dt = item.event_date
    date_prefix = dt.strftime("%Y-%m-%d %H-%M-%S")

    for f in os.listdir(audio_dir):
        if f.startswith(date_prefix) and not f.endswith(".json"):
            return os.path.join(audio_dir, f)

    return None


def parse_caller_from_title(title):
    """Extract caller name from evidence title."""
    if "Kelly Smakel" in title or "Melissa Attorney" in title:
        return "Kelly Smakel (Melissa's Attorney)"
    if "Alice" in title and "Therapist" in title:
        return "Alice (Therapist)"
    if "Melissa" in title:
        return "Melissa"
    return "Unknown"


def main():
    app = create_app()
    print("Initializing Claude AI...")
    client = get_anthropic_client()
    print("Loading whisper model (first run downloads ~150MB)...")

    transcripts_dir = os.path.join(os.path.dirname(INBOX), "transcripts")
    os.makedirs(transcripts_dir, exist_ok=True)

    with app.app_context():
        # Find all audio/voicemail items without transcripts
        items = EvidenceItem.query.filter(
            EvidenceItem.evidence_type.in_(["audio", "voicemail"]),
            (EvidenceItem.transcript == None) | (EvidenceItem.transcript == ""),
        ).order_by(EvidenceItem.event_date).all()

        print(f"\nFound {len(items)} audio items needing transcription.\n")

        transcribed = 0
        failed = 0

        for i, item in enumerate(items):
            print(f"\n[{i+1}/{len(items)}] {item.title[:70]}")
            print(f"  Date: {item.event_date.strftime('%Y-%m-%d %I:%M %p')}")

            # Find original audio file
            source = find_source_audio(item)
            if not source:
                print(f"  SKIP: Source audio not found in inbox")
                failed += 1
                continue

            ext = os.path.splitext(source)[1].lower()
            size_mb = os.path.getsize(source) / (1024 * 1024)
            print(f"  File: {os.path.basename(source)} ({size_mb:.1f} MB, {ext})")

            # Transcribe
            print(f"  Transcribing...")
            transcript = transcribe_file(source)

            if not transcript or len(transcript.strip()) < 10:
                print(f"  SKIP: Transcription produced no usable text")
                failed += 1
                continue

            word_count = len(transcript.split())
            print(f"  Transcript: {word_count} words")

            # Save transcript to item
            item.transcript = transcript

            # Parse metadata for AI
            json_path = source.rsplit(".", 1)[0] + ".json"
            direction = "Unknown"
            duration_min = 0
            if os.path.exists(json_path):
                with open(json_path, "r") as f:
                    meta = json.load(f)
                direction = meta.get("direction", "Unknown")
                duration_min = int(meta.get("duration", 0)) / 60000
            else:
                # Try matching .json by date prefix
                date_prefix = item.event_date.strftime("%Y-%m-%d %H-%M-%S")
                audio_dir = os.path.join(INBOX, "audio")
                for jf in os.listdir(audio_dir):
                    if jf.startswith(date_prefix) and jf.endswith(".json"):
                        with open(os.path.join(audio_dir, jf)) as f:
                            meta = json.load(f)
                        direction = meta.get("direction", "Unknown")
                        duration_min = int(meta.get("duration", 0)) / 60000
                        break

            caller = parse_caller_from_title(item.title)

            # AI re-analysis with actual transcript
            print(f"  Analyzing with Claude...")
            analysis = analyze_with_claude(client, transcript, direction, duration_min, caller, item.event_date)

            if analysis:
                item.title = analysis.get("title", item.title)
                item.category = analysis["category"]
                item.subcategories = json.dumps(analysis.get("subcategories", [])) or None
                item.severity = analysis["severity"]
                item.child_present = analysis.get("child_present", False)
                item.key_quotes = json.dumps(analysis.get("key_quotes", [])) or None
                item.description = analysis.get("description")
                item.people_present = analysis.get("people_present")
                item.tags = json.dumps(analysis.get("tags", [])) or None

                cat_label = EVIDENCE_CATEGORIES.get(item.category, {}).get("label", item.category)
                print(f"  Result: {cat_label}, severity={item.severity}")
                if analysis.get("key_quotes"):
                    for q in analysis["key_quotes"][:2]:
                        print(f"    \"{q[:80]}\"")

            # Save transcript to file
            safe_title = re.sub(r'[<>:"/\\|?*]', '_', item.title)[:80]
            t_path = os.path.join(transcripts_dir,
                                  f"{item.event_date.strftime('%Y-%m-%d_%H%M')}_{safe_title}.txt")
            with open(t_path, "w", encoding="utf-8") as f:
                f.write(f"TRANSCRIPT: {item.title}\n")
                f.write(f"Date: {item.event_date.strftime('%Y-%m-%d %I:%M %p')}\n")
                f.write(f"Direction: {direction} | Duration: {duration_min:.1f} min\n")
                f.write(f"Caller: {caller}\n")
                if analysis:
                    f.write(f"Category: {EVIDENCE_CATEGORIES.get(item.category, {}).get('label', '')}\n")
                    f.write(f"Severity: {item.severity}/5\n")
                f.write(f"{'='*60}\n\n")
                f.write(transcript)

            db.session.commit()
            transcribed += 1
            print(f"  DONE ({transcribed} transcribed so far)")

    print(f"\n{'='*60}")
    print(f"  TRANSCRIPTION COMPLETE")
    print(f"  Transcribed: {transcribed}")
    print(f"  Failed: {failed}")
    print(f"  Transcripts saved to: C:/Projects/Evidence/transcripts/")
    print(f"  View at: http://localhost:5050/timeline")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
