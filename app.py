import os
import json
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, Response, stream_with_context
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

db = SQLAlchemy()

# ---------------------------------------------------------------------------
# Evidence Categories — custody case taxonomy
# ---------------------------------------------------------------------------
EVIDENCE_CATEGORIES = {
    "parental_alienation": {
        "label": "Parental Alienation",
        "color": "#e74c3c",
        "icon": "🚫",
        "description": "Statements or actions turning the child against the other parent",
        "examples": [
            "Telling the child the other parent doesn't love them",
            "Making the child feel guilty for enjoying time with other parent",
            "Sharing adult conflict details with the child",
            "Encouraging the child to spy or report on the other parent",
        ],
    },
    "false_accusations": {
        "label": "False Accusations",
        "color": "#e67e22",
        "icon": "⚠️",
        "description": "Unfounded claims made to authorities, family, or the child",
        "examples": [
            "False abuse allegations",
            "Fabricated safety concerns",
            "Untrue claims to police, CPS, or courts",
            "Exaggerated or distorted incidents",
        ],
    },
    "communication_interference": {
        "label": "Communication Interference",
        "color": "#9b59b6",
        "icon": "📵",
        "description": "Blocking, restricting, or sabotaging co-parenting communication",
        "examples": [
            "Not responding to texts or calls about the child",
            "Blocking phone numbers",
            "Refusing to use co-parenting apps",
            "Intercepting child's communication with other parent",
        ],
    },
    "verbal_abuse": {
        "label": "Verbal Abuse / Yelling / Name-Calling",
        "color": "#c0392b",
        "icon": "🗯️",
        "description": "Hostile, demeaning, or threatening verbal conduct",
        "examples": [
            "Yelling during exchanges",
            "Name-calling in front of children",
            "Threatening language in texts or voicemails",
            "Demeaning remarks about parenting ability",
        ],
    },
    "withholding": {
        "label": "Withholding",
        "color": "#2c3e50",
        "icon": "🔒",
        "description": "Withholding access, information, or cooperation",
        "examples": [
            "Withholding medical or school information",
            "Denying scheduled parenting time",
            "Not sharing extracurricular schedules",
            "Withholding the child's belongings",
        ],
    },
    "gatekeeping": {
        "label": "Gatekeeping",
        "color": "#8e44ad",
        "icon": "🚧",
        "description": "Unilateral control over parenting decisions",
        "examples": [
            "Making major decisions without consulting the other parent",
            "Controlling who the child can see during the other parent's time",
            "Scheduling activities during the other parent's time without consent",
            "Refusing to allow phone or video calls",
        ],
    },
    "schedule_violations": {
        "label": "Schedule / Order Violations",
        "color": "#d35400",
        "icon": "📅",
        "description": "Violations of custody orders, schedules, or agreements",
        "examples": [
            "Late pickups or drop-offs",
            "Not returning the child on time",
            "Canceling parenting time last minute",
            "Refusing exchanges",
        ],
    },
    "emotional_manipulation": {
        "label": "Emotional Manipulation",
        "color": "#c27ba0",
        "icon": "🎭",
        "description": "Guilt, fear, or loyalty conflicts imposed on the child or other parent",
        "examples": [
            "Making the child choose sides",
            "Crying or guilt-tripping the child during transitions",
            "Using the child as a messenger",
            "Rewarding the child for rejecting the other parent",
        ],
    },
    "documentation_of_cooperation": {
        "label": "Cooperation Attempts (Your Good Faith)",
        "color": "#27ae60",
        "icon": "✅",
        "description": "Evidence of your attempts to co-parent, communicate, and cooperate",
        "examples": [
            "Reasonable text messages sent",
            "Offers to compromise or mediate",
            "Following the parenting plan consistently",
            "Attending school events and medical appointments",
        ],
    },
    "impact_on_child": {
        "label": "Impact on Child",
        "color": "#2980b9",
        "icon": "👶",
        "description": "Observable effects on the child's behavior, wellbeing, or statements",
        "examples": [
            "Child repeating coached statements",
            "Behavioral changes after exchanges",
            "Child expressing fear or anxiety about visits",
            "Regression in school performance",
        ],
    },
    "financial_abuse": {
        "label": "Financial Interference",
        "color": "#f39c12",
        "icon": "💰",
        "description": "Using money as a weapon or failing financial obligations",
        "examples": [
            "Withholding child support",
            "Hiding income or assets",
            "Refusing to share child-related expenses",
            "Making large purchases to appear more favorable",
        ],
    },
    "third_party_witness": {
        "label": "Third-Party Witness / Corroboration",
        "color": "#1abc9c",
        "icon": "👥",
        "description": "Statements from teachers, therapists, family, or other witnesses",
        "examples": [
            "Teacher reports about child's behavior",
            "Therapist observations",
            "Family member statements",
            "Neighbor or friend accounts of incidents",
        ],
    },
}

EVIDENCE_TYPES = {
    "audio": {"label": "Audio Recording", "icon": "🎙️", "accept": ".mp3,.wav,.m4a,.ogg,.webm,.mp4,.aac"},
    "text_message": {"label": "Text Message / Chat", "icon": "💬", "accept": ".txt,.pdf,.png,.jpg,.jpeg"},
    "email": {"label": "Email", "icon": "📧", "accept": ".txt,.pdf,.eml,.png,.jpg,.jpeg"},
    "journal": {"label": "Journal Entry", "icon": "📝", "accept": None},
    "screenshot": {"label": "Screenshot", "icon": "📸", "accept": ".png,.jpg,.jpeg,.gif,.webp"},
    "document": {"label": "Document / Court Filing", "icon": "📄", "accept": ".pdf,.docx,.txt,.png,.jpg"},
    "video": {"label": "Video", "icon": "🎥", "accept": ".mp4,.mov,.avi,.webm"},
    "voicemail": {"label": "Voicemail", "icon": "📞", "accept": ".mp3,.wav,.m4a,.ogg,.aac"},
    "witness_statement": {"label": "Witness Statement", "icon": "🗣️", "accept": ".pdf,.docx,.txt"},
    "calendar": {"label": "Calendar / Schedule Record", "icon": "📆", "accept": ".pdf,.png,.jpg,.ics"},
}

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class EvidenceItem(db.Model):
    __tablename__ = "evidence_items"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text)
    evidence_type = db.Column(db.String(50), nullable=False)  # audio, text_message, journal, etc.
    category = db.Column(db.String(50), nullable=False)  # parental_alienation, verbal_abuse, etc.
    subcategories = db.Column(db.Text)  # JSON list of additional categories
    event_date = db.Column(db.DateTime, nullable=False)
    file_path = db.Column(db.String(1000))
    transcript = db.Column(db.Text)
    raw_text = db.Column(db.Text)  # original text content (for text messages, journals, etc.)
    key_quotes = db.Column(db.Text)  # JSON list of important quotes from this evidence
    severity = db.Column(db.Integer, default=3)  # 1-5 scale
    people_present = db.Column(db.String(500))
    child_present = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)
    tags = db.Column(db.Text)  # JSON list of tags
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def category_info(self):
        return EVIDENCE_CATEGORIES.get(self.category, {})

    @property
    def type_info(self):
        return EVIDENCE_TYPES.get(self.evidence_type, {})

    @property
    def subcategory_list(self):
        if self.subcategories:
            return json.loads(self.subcategories)
        return []

    @property
    def quote_list(self):
        if self.key_quotes:
            return json.loads(self.key_quotes)
        return []

    @property
    def tag_list(self):
        if self.tags:
            return json.loads(self.tags)
        return []


class FeatureSuggestion(db.Model):
    """User-submitted feature suggestions."""
    __tablename__ = "feature_suggestions"
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default="open")  # open, completed, removed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)


class Exhibit(db.Model):
    """A numbered exhibit grouping evidence items with a cover sheet narrative."""
    __tablename__ = "exhibits"
    id = db.Column(db.Integer, primary_key=True)
    letter = db.Column(db.String(5), nullable=False)  # A, B, C, ...
    title = db.Column(db.String(500), nullable=False)
    category = db.Column(db.String(50))
    narrative = db.Column(db.Text)  # Cover sheet narrative
    evidence_ids = db.Column(db.Text)  # JSON list of evidence IDs
    date_range_start = db.Column(db.DateTime)
    date_range_end = db.Column(db.DateTime)
    incident_count = db.Column(db.Integer, default=0)
    child_present_count = db.Column(db.Integer, default=0)
    max_severity = db.Column(db.Integer, default=0)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def evidence_id_list(self):
        if self.evidence_ids:
            return json.loads(self.evidence_ids)
        return []


class Claim(db.Model):
    """A pattern-of-behavior claim supported by multiple evidence items."""
    __tablename__ = "claims"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(500), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    summary = db.Column(db.Text)
    date_range_start = db.Column(db.DateTime)
    date_range_end = db.Column(db.DateTime)
    evidence_ids = db.Column(db.Text)  # JSON list of evidence IDs
    strength = db.Column(db.String(20))  # strong, moderate, developing
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def evidence_id_list(self):
        if self.evidence_ids:
            return json.loads(self.evidence_ids)
        return []


class RecordingNote(db.Model):
    """A timestamped note on an audio recording."""
    __tablename__ = "recording_notes"
    id = db.Column(db.Integer, primary_key=True)
    evidence_id = db.Column(db.Integer, db.ForeignKey("evidence_items.id"), nullable=False)
    timestamp_seconds = db.Column(db.Float, default=0)  # playback position in seconds
    note_type = db.Column(db.String(30), default="note")  # note, question, important, action
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    evidence = db.relationship("EvidenceItem", backref="recording_notes")

    @property
    def timestamp_formatted(self):
        m = int(self.timestamp_seconds // 60)
        s = int(self.timestamp_seconds % 60)
        return f"{m:02d}:{s:02d}"


class Conversation(db.Model):
    """AI Counsel chat conversation."""
    __tablename__ = "counsel_conversations"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(500), default="New Conversation")
    mode = db.Column(db.String(30), default="general")  # general, exhibit, pattern, timeline
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    messages = db.relationship("Message", backref="conversation", lazy=True, order_by="Message.created_at")


class Message(db.Model):
    """A single message in a counsel conversation."""
    __tablename__ = "counsel_messages"
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("counsel_conversations.id"), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # user, assistant
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Knowledge Base Builder
# ---------------------------------------------------------------------------
def build_knowledge_base():
    """Compile all evidence into a structured context string for Claude."""
    items = EvidenceItem.query.order_by(EvidenceItem.event_date.asc()).all()
    claims = Claim.query.all()
    exhibits = Exhibit.query.order_by(Exhibit.sort_order.asc()).all()

    total = len(items)
    if total == 0:
        return "No evidence has been entered yet."

    # Summary stats
    cat_counts = {}
    for item in items:
        label = EVIDENCE_CATEGORIES.get(item.category, {}).get("label", item.category)
        cat_counts[label] = cat_counts.get(label, 0) + 1

    date_range_start = items[0].event_date.strftime("%B %d, %Y")
    date_range_end = items[-1].event_date.strftime("%B %d, %Y")
    child_present_count = sum(1 for i in items if i.child_present)
    high_severity_count = sum(1 for i in items if i.severity >= 4)

    parts = []
    parts.append("=" * 60)
    parts.append("EVIDENCE KNOWLEDGE BASE")
    parts.append("=" * 60)
    parts.append(f"\nTotal evidence items: {total}")
    parts.append(f"Date range: {date_range_start} to {date_range_end}")
    parts.append(f"High severity incidents (4-5): {high_severity_count}")
    parts.append(f"Incidents where child was present: {child_present_count}")
    parts.append("\nBreakdown by category:")
    for label, count in sorted(cat_counts.items(), key=lambda x: x[1], reverse=True):
        parts.append(f"  - {label}: {count}")

    # Each evidence item — truncate long fields to fit context window
    MAX_TEXT_LEN = 500  # max chars per text field

    def truncate(text, max_len=MAX_TEXT_LEN):
        if not text:
            return text
        if len(text) <= max_len:
            return text
        return text[:max_len] + f"... [truncated, {len(text)} chars total]"

    parts.append("\n" + "=" * 60)
    parts.append("EVIDENCE ITEMS (chronological)")
    parts.append("=" * 60)

    for item in items:
        cat_label = EVIDENCE_CATEGORIES.get(item.category, {}).get("label", item.category)
        type_label = EVIDENCE_TYPES.get(item.evidence_type, {}).get("label", item.evidence_type)
        parts.append(f"\n--- Evidence #{item.id} ---")
        parts.append(f"Title: {item.title}")
        parts.append(f"Date: {item.event_date.strftime('%Y-%m-%d %I:%M %p')}")
        parts.append(f"Category: {cat_label} | Type: {type_label} | Severity: {item.severity}/5 | Child: {'Yes' if item.child_present else 'No'}")
        if item.people_present:
            parts.append(f"People: {item.people_present}")
        if item.description:
            parts.append(f"Description: {truncate(item.description)}")
        if item.raw_text:
            parts.append(f"Text: {truncate(item.raw_text, 400)}")
        if item.transcript:
            parts.append(f"Transcript: {truncate(item.transcript, 400)}")
        if item.quote_list:
            parts.append("Quotes: " + " | ".join(f'"{q}"' for q in item.quote_list[:3]))
        if item.tag_list:
            parts.append(f"Tags: {', '.join(item.tag_list)}")
        if item.notes:
            parts.append(f"Notes: {truncate(item.notes, 200)}")

    # Claims
    if claims:
        parts.append("\n" + "=" * 60)
        parts.append("PATTERN CLAIMS")
        parts.append("=" * 60)
        for claim in claims:
            parts.append(f"\nClaim: {claim.title}")
            parts.append(f"Category: {claim.category}")
            parts.append(f"Strength: {claim.strength}")
            parts.append(f"Summary: {claim.summary}")
            parts.append(f"Supporting evidence IDs: {claim.evidence_id_list}")

    # Exhibits
    if exhibits:
        parts.append("\n" + "=" * 60)
        parts.append("GENERATED EXHIBITS")
        parts.append("=" * 60)
        for exhibit in exhibits:
            parts.append(f"\nExhibit {exhibit.letter}: {exhibit.title}")
            parts.append(f"Category: {exhibit.category}")
            parts.append(f"Incidents: {exhibit.incident_count}")
            parts.append(f"Narrative: {exhibit.narrative}")

    return "\n".join(parts)


COUNSEL_SYSTEM_PROMPT = """You are an AI legal research assistant embedded in a custody case evidence platform. You have access to the complete evidence knowledge base for this case.

Your role:
- Analyze evidence patterns and help identify relevant patterns of behavior
- Draft exhibit narratives for court presentation
- Answer questions about specific evidence items, timelines, and categories
- Identify gaps in documentation or areas needing more evidence
- Suggest how evidence supports or relates to legal arguments
- Summarize key incidents by category, severity, or time period

Important guidelines:
- You are NOT providing legal advice. You are analyzing evidence and helping organize it.
- Always reference specific evidence item numbers (e.g., "Evidence #42") when citing evidence.
- When drafting exhibits, use formal, objective language suitable for court filings.
- Flag when the child was present in incidents as this is legally significant.
- Severity ratings: 1=minor, 2=notable, 3=moderate, 4=serious, 5=safety concern.
- Be thorough but concise. Courts value clarity.

The evidence categories in this case are:
- Parental Alienation
- False Accusations
- Communication Interference
- Verbal Abuse / Yelling / Name-Calling
- Withholding
- Gatekeeping
- Schedule / Order Violations
- Emotional Manipulation
- Cooperation Attempts (documenting good faith efforts)
- Impact on Child
- Financial Interference
- Third-Party Witness / Corroboration
"""


def get_anthropic_client():
    """Get Anthropic client with API key from env or SunoSmart .env."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        # Try SunoSmart .env as fallback
        dotenv_path = os.path.join(os.path.dirname(__file__), "..", "KingdomBuilders.AI", "SunoSmart", ".env")
        if os.path.exists(dotenv_path):
            with open(dotenv_path) as f:
                for line in f:
                    if line.startswith("ANTHROPIC_API_KEY="):
                        api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
    if not api_key:
        return None
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


# ---------------------------------------------------------------------------
# App Factory
# ---------------------------------------------------------------------------
def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "evidence-dev-key-change-in-prod")
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        # Render provides postgres:// but SQLAlchemy needs postgresql://
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    else:
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///evidence.db"
    app.config["UPLOAD_FOLDER"] = os.path.join(os.path.dirname(__file__), "uploads")
    app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500MB for video/audio

    # URL prefix for reverse proxy (e.g. kingdombuilders.ai/evidence)
    url_prefix = os.environ.get("URL_PREFIX", "")
    if url_prefix:
        class PrefixMiddleware:
            def __init__(self, wsgi_app, prefix):
                self.app = wsgi_app
                self.prefix = prefix
            def __call__(self, environ, start_response):
                path = environ.get("PATH_INFO", "")
                if path.startswith(self.prefix):
                    environ["PATH_INFO"] = path[len(self.prefix):] or "/"
                    environ["SCRIPT_NAME"] = self.prefix
                return self.app(environ, start_response)
        app.wsgi_app = PrefixMiddleware(app.wsgi_app, url_prefix)

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)

    with app.app_context():
        db.create_all()

    # -- Context processors --
    @app.context_processor
    def inject_globals():
        return {
            "categories": EVIDENCE_CATEGORIES,
            "evidence_types": EVIDENCE_TYPES,
            "now": datetime.utcnow(),
            "prefix": url_prefix,
        }

    # Rewrite hardcoded URLs in HTML responses when behind a prefix
    if url_prefix:
        import re as _re
        _prefix_pat = _re.compile(
            r'((?:href|action|src)=["\'])/'
        )
        _double_pat = _re.compile(
            r'((?:href|action|src)=["\'])' + _re.escape(url_prefix) + _re.escape(url_prefix)
        )
        @app.after_request
        def rewrite_urls(response):
            if response.content_type and "text/html" in response.content_type:
                content = response.get_data(as_text=True)
                # Prefix all absolute paths
                content = _prefix_pat.sub(rf'\g<1>{url_prefix}/', content)
                # Fix any double-prefixed URLs (from url_for + rewrite)
                content = _double_pat.sub(rf'\g<1>{url_prefix}', content)
                # Don't prefix external URLs (https://)
                content = content.replace(f'{url_prefix}//', '//')
                response.set_data(content)
            return response

    # -- Routes --

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/intake", methods=["GET"])
    def intake():
        return render_template("intake.html")

    @app.route("/intake/submit", methods=["POST"])
    def intake_submit():
        title = request.form.get("title", "").strip()
        evidence_type = request.form.get("evidence_type")
        category = request.form.get("category")
        event_date_str = request.form.get("event_date")
        description = request.form.get("description", "").strip()
        raw_text = request.form.get("raw_text", "").strip()
        key_quotes_raw = request.form.get("key_quotes", "").strip()
        severity = int(request.form.get("severity", 3))
        people_present = request.form.get("people_present", "").strip()
        child_present = request.form.get("child_present") == "on"
        notes = request.form.get("notes", "").strip()
        tags_raw = request.form.get("tags", "").strip()

        subcats = request.form.getlist("subcategories")

        # Parse date
        try:
            event_date = datetime.fromisoformat(event_date_str)
        except (ValueError, TypeError):
            event_date = datetime.utcnow()

        # Handle file upload
        file_path = None
        file = request.files.get("file")
        if file and file.filename:
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp}_{filename}"
            subfolder = "audio" if evidence_type in ("audio", "voicemail") else "documents"
            if evidence_type == "screenshot":
                subfolder = "screenshots"
            save_dir = os.path.join(app.config["UPLOAD_FOLDER"], subfolder)
            os.makedirs(save_dir, exist_ok=True)
            full_path = os.path.join(save_dir, filename)
            file.save(full_path)
            file_path = f"uploads/{subfolder}/{filename}"

        # Parse key quotes into list
        key_quotes = []
        if key_quotes_raw:
            key_quotes = [q.strip() for q in key_quotes_raw.split("\n") if q.strip()]

        # Parse tags
        tag_list = []
        if tags_raw:
            tag_list = [t.strip() for t in tags_raw.split(",") if t.strip()]

        item = EvidenceItem(
            title=title,
            description=description,
            evidence_type=evidence_type,
            category=category,
            subcategories=json.dumps(subcats) if subcats else None,
            event_date=event_date,
            file_path=file_path,
            raw_text=raw_text or None,
            key_quotes=json.dumps(key_quotes) if key_quotes else None,
            severity=severity,
            people_present=people_present or None,
            child_present=child_present,
            notes=notes or None,
            tags=json.dumps(tag_list) if tag_list else None,
        )
        db.session.add(item)
        db.session.commit()
        flash(f"Evidence #{item.id} saved: {title}", "success")
        return redirect(url_for("intake"))

    @app.route("/timeline")
    def timeline():
        category_filter = request.args.get("category")
        type_filter = request.args.get("type")
        search = request.args.get("q", "").strip()
        severity_min = request.args.get("severity_min", type=int)

        query = EvidenceItem.query
        if category_filter:
            query = query.filter(EvidenceItem.category == category_filter)
        if type_filter:
            query = query.filter(EvidenceItem.evidence_type == type_filter)
        if severity_min:
            query = query.filter(EvidenceItem.severity >= severity_min)
        if search:
            like = f"%{search}%"
            query = query.filter(
                db.or_(
                    EvidenceItem.title.ilike(like),
                    EvidenceItem.description.ilike(like),
                    EvidenceItem.raw_text.ilike(like),
                    EvidenceItem.transcript.ilike(like),
                    EvidenceItem.key_quotes.ilike(like),
                    EvidenceItem.notes.ilike(like),
                    EvidenceItem.tags.ilike(like),
                )
            )

        items = query.order_by(EvidenceItem.event_date.asc()).all()
        return render_template("timeline.html", items=items,
                               category_filter=category_filter,
                               type_filter=type_filter,
                               search=search,
                               severity_min=severity_min)

    @app.route("/evidence/<int:item_id>")
    def evidence_detail(item_id):
        item = EvidenceItem.query.get_or_404(item_id)
        return render_template("detail.html", item=item)

    @app.route("/evidence/<int:item_id>/edit", methods=["GET", "POST"])
    def evidence_edit(item_id):
        item = EvidenceItem.query.get_or_404(item_id)
        if request.method == "POST":
            item.title = request.form.get("title", item.title)
            item.description = request.form.get("description", "").strip() or None
            item.evidence_type = request.form.get("evidence_type", item.evidence_type)
            item.category = request.form.get("category", item.category)
            item.raw_text = request.form.get("raw_text", "").strip() or None
            item.transcript = request.form.get("transcript", "").strip() or None
            item.severity = int(request.form.get("severity", 3))
            item.people_present = request.form.get("people_present", "").strip() or None
            item.child_present = request.form.get("child_present") == "on"
            item.notes = request.form.get("notes", "").strip() or None

            key_quotes_raw = request.form.get("key_quotes", "").strip()
            if key_quotes_raw:
                item.key_quotes = json.dumps([q.strip() for q in key_quotes_raw.split("\n") if q.strip()])

            tags_raw = request.form.get("tags", "").strip()
            if tags_raw:
                item.tags = json.dumps([t.strip() for t in tags_raw.split(",") if t.strip()])

            subcats = request.form.getlist("subcategories")
            item.subcategories = json.dumps(subcats) if subcats else None

            try:
                item.event_date = datetime.fromisoformat(request.form.get("event_date"))
            except (ValueError, TypeError):
                pass

            db.session.commit()
            flash(f"Evidence #{item.id} updated.", "success")
            return redirect(url_for("evidence_detail", item_id=item.id))
        return render_template("edit.html", item=item)

    @app.route("/claims")
    def claims_list():
        claims = Claim.query.order_by(Claim.created_at.desc()).all()
        return render_template("claims.html", claims=claims)

    @app.route("/claims/new", methods=["GET", "POST"])
    def claim_new():
        if request.method == "POST":
            evidence_ids = request.form.getlist("evidence_ids")
            claim = Claim(
                title=request.form.get("title"),
                category=request.form.get("category"),
                summary=request.form.get("summary"),
                strength=request.form.get("strength", "developing"),
                evidence_ids=json.dumps([int(x) for x in evidence_ids]) if evidence_ids else "[]",
            )
            if request.form.get("date_range_start"):
                claim.date_range_start = datetime.fromisoformat(request.form["date_range_start"])
            if request.form.get("date_range_end"):
                claim.date_range_end = datetime.fromisoformat(request.form["date_range_end"])
            db.session.add(claim)
            db.session.commit()
            flash(f"Claim created: {claim.title}", "success")
            return redirect(url_for("claims_list"))
        items = EvidenceItem.query.order_by(EvidenceItem.event_date.asc()).all()
        return render_template("claim_new.html", items=items)

    @app.route("/claims/<int:claim_id>")
    def claim_detail(claim_id):
        claim = Claim.query.get_or_404(claim_id)
        evidence = EvidenceItem.query.filter(EvidenceItem.id.in_(claim.evidence_id_list)).order_by(EvidenceItem.event_date.asc()).all()
        return render_template("claim_detail.html", claim=claim, evidence=evidence)

    @app.route("/dashboard")
    def dashboard():
        total = EvidenceItem.query.count()
        by_category = {}
        for cat_key in EVIDENCE_CATEGORIES:
            by_category[cat_key] = EvidenceItem.query.filter_by(category=cat_key).count()
        by_type = {}
        for type_key in EVIDENCE_TYPES:
            by_type[type_key] = EvidenceItem.query.filter_by(evidence_type=type_key).count()
        claims_count = Claim.query.count()
        recent = EvidenceItem.query.order_by(EvidenceItem.created_at.desc()).limit(10).all()
        return render_template("dashboard.html", total=total, by_category=by_category,
                               by_type=by_type, claims_count=claims_count, recent=recent)

    @app.route("/search")
    def search():
        import re as _search_re
        q = request.args.get("q", "").strip()
        category_filter = request.args.get("category")
        type_filter = request.args.get("type")
        severity_min = request.args.get("severity_min", type=int)
        results = []
        exact = False
        search_term = q

        if q:
            # Detect double-quoted exact search
            match = _search_re.match(r'^"(.+)"$', q)
            if match:
                exact = True
                search_term = match.group(1)

            # Search all text fields on every item
            searchable_fields = ["title", "description", "raw_text", "transcript",
                                 "key_quotes", "notes", "tags", "people_present"]

            query = EvidenceItem.query
            if category_filter:
                query = query.filter(EvidenceItem.category == category_filter)
            if type_filter:
                query = query.filter(EvidenceItem.evidence_type == type_filter)
            if severity_min:
                query = query.filter(EvidenceItem.severity >= severity_min)

            all_items = query.order_by(EvidenceItem.event_date.asc()).all()

            for item in all_items:
                matched_fields = []
                matched_snippets = []
                for field_name in searchable_fields:
                    value = getattr(item, field_name, None)
                    if not value:
                        continue
                    if exact:
                        # Case-insensitive exact phrase match
                        if search_term.lower() in value.lower():
                            matched_fields.append(field_name)
                            # Extract snippet around match
                            idx = value.lower().index(search_term.lower())
                            start = max(0, idx - 80)
                            end = min(len(value), idx + len(search_term) + 80)
                            snippet = value[start:end]
                            if start > 0:
                                snippet = "..." + snippet
                            if end < len(value):
                                snippet = snippet + "..."
                            matched_snippets.append((field_name, snippet))
                    else:
                        # Substring: all words must appear (AND logic)
                        words = search_term.lower().split()
                        val_lower = value.lower()
                        if all(w in val_lower for w in words):
                            matched_fields.append(field_name)
                            # Find first word occurrence for snippet
                            idx = val_lower.index(words[0])
                            start = max(0, idx - 80)
                            end = min(len(value), idx + len(words[0]) + 120)
                            snippet = value[start:end]
                            if start > 0:
                                snippet = "..." + snippet
                            if end < len(value):
                                snippet = snippet + "..."
                            matched_snippets.append((field_name, snippet))

                if matched_fields:
                    results.append({
                        "item": item,
                        "matched_fields": matched_fields,
                        "snippets": matched_snippets,
                    })

        return render_template("search.html", q=q, results=results, exact=exact,
                               search_term=search_term, category_filter=category_filter,
                               type_filter=type_filter, severity_min=severity_min)

    @app.route("/print/timeline")
    def print_timeline():
        category_filter = request.args.get("category")
        query = EvidenceItem.query
        if category_filter:
            query = query.filter(EvidenceItem.category == category_filter)
        items = query.order_by(EvidenceItem.event_date.asc()).all()
        return render_template("print_timeline.html", items=items, category_filter=category_filter)

    @app.route("/print/claim/<int:claim_id>")
    def print_claim(claim_id):
        claim = Claim.query.get_or_404(claim_id)
        evidence = EvidenceItem.query.filter(EvidenceItem.id.in_(claim.evidence_id_list)).order_by(EvidenceItem.event_date.asc()).all()
        return render_template("print_claim.html", claim=claim, evidence=evidence)

    @app.route("/print/evidence/<int:item_id>")
    def print_evidence(item_id):
        item = EvidenceItem.query.get_or_404(item_id)
        return render_template("print_evidence.html", item=item)

    @app.route("/api/evidence")
    def api_evidence():
        items = EvidenceItem.query.order_by(EvidenceItem.event_date.asc()).all()
        return jsonify([{
            "id": i.id,
            "title": i.title,
            "category": i.category,
            "category_label": i.category_info.get("label", ""),
            "category_color": i.category_info.get("color", "#666"),
            "evidence_type": i.evidence_type,
            "event_date": i.event_date.isoformat(),
            "severity": i.severity,
            "child_present": i.child_present,
            "key_quotes": i.quote_list,
            "description": i.description or "",
        } for i in items])

    @app.route("/transcribe/<int:item_id>", methods=["POST"])
    def transcribe(item_id):
        item = EvidenceItem.query.get_or_404(item_id)
        if not item.file_path:
            flash("No file attached to transcribe.", "error")
            return redirect(url_for("evidence_detail", item_id=item_id))
        try:
            from faster_whisper import WhisperModel
            model = WhisperModel("base", device="cpu")
            full_path = os.path.join(os.path.dirname(__file__), item.file_path)
            segments, info = model.transcribe(full_path)
            transcript_lines = []
            for seg in segments:
                minutes = int(seg.start // 60)
                seconds = int(seg.start % 60)
                transcript_lines.append(f"[{minutes:02d}:{seconds:02d}] {seg.text.strip()}")
            item.transcript = "\n".join(transcript_lines)
            db.session.commit()

            # Also save to transcripts folder
            safe_title = secure_filename(item.title)
            transcript_path = os.path.join(os.path.dirname(__file__), "transcripts", f"{safe_title}.txt")
            with open(transcript_path, "w", encoding="utf-8") as f:
                f.write(f"TRANSCRIPT: {item.title}\n")
                f.write(f"Date: {item.event_date.strftime('%Y-%m-%d %I:%M %p')}\n")
                f.write(f"Category: {item.category_info.get('label', '')}\n")
                f.write(f"{'='*60}\n\n")
                f.write(item.transcript)
            flash(f"Transcription complete. Saved to transcripts/{safe_title}.txt", "success")
        except ImportError:
            flash("faster-whisper not installed. Run: pip install faster-whisper", "error")
        except Exception as e:
            flash(f"Transcription error: {str(e)}", "error")
        return redirect(url_for("evidence_detail", item_id=item_id))

    @app.route("/uploads/<path:filename>")
    def serve_upload(filename):
        from flask import send_from_directory
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    @app.route("/audio-evidence")
    def audio_evidence():
        category_filter = request.args.get("category")
        severity_min = request.args.get("severity_min", type=int)
        search = request.args.get("q", "").strip()

        query = EvidenceItem.query.filter(
            EvidenceItem.evidence_type.in_(["audio", "voicemail"]),
            EvidenceItem.transcript.isnot(None),
        )
        if category_filter:
            query = query.filter(EvidenceItem.category == category_filter)
        if severity_min:
            query = query.filter(EvidenceItem.severity >= severity_min)
        if search:
            query = query.filter(EvidenceItem.transcript.ilike(f"%{search}%"))

        items = query.order_by(EvidenceItem.event_date.asc()).all()

        # Build structured data for template
        recordings = []
        for item in items:
            lines = []
            for line in (item.transcript or "").strip().split("\n"):
                if line.startswith("[") and "]" in line:
                    ts_str = line.split("]")[0].replace("[", "").strip()
                    text = line.split("]", 1)[1].strip()
                    parts = ts_str.split(":")
                    seconds = int(parts[0]) * 60 + int(parts[1]) if len(parts) == 2 else 0
                    lines.append({"ts": ts_str, "seconds": seconds, "text": text})
            recordings.append({
                "item": item,
                "lines": lines,
            })
        return render_template("audio_evidence.html", recordings=recordings,
                               category_filter=category_filter,
                               severity_min=severity_min, search=search)

    @app.route("/api/audio-evidence")
    def api_audio_evidence():
        items = EvidenceItem.query.filter(
            EvidenceItem.evidence_type.in_(["audio", "voicemail"]),
            EvidenceItem.transcript.isnot(None),
        ).order_by(EvidenceItem.event_date.asc()).all()
        result = []
        for item in items:
            lines = []
            for line in (item.transcript or "").strip().split("\n"):
                if line.startswith("[") and "]" in line:
                    ts_str = line.split("]")[0].replace("[", "").strip()
                    text = line.split("]", 1)[1].strip()
                    parts = ts_str.split(":")
                    seconds = int(parts[0]) * 60 + int(parts[1]) if len(parts) == 2 else 0
                    lines.append({"ts": ts_str, "seconds": seconds, "text": text})
            result.append({
                "id": item.id,
                "title": item.title,
                "date": item.event_date.isoformat(),
                "category": item.category,
                "category_label": item.category_info.get("label", ""),
                "category_color": item.category_info.get("color", "#666"),
                "severity": item.severity,
                "child_present": item.child_present,
                "file_path": item.file_path,
                "key_quotes": item.quote_list,
                "description": item.description or "",
                "people_present": item.people_present or "",
                "lines": lines,
            })
        return jsonify(result)

    # -- Exhibit Builder --

    @app.route("/exhibits")
    def exhibits_list():
        exhibits = Exhibit.query.order_by(Exhibit.sort_order.asc()).all()
        return render_template("exhibits.html", exhibits=exhibits)

    @app.route("/exhibits/generate", methods=["POST"])
    def exhibits_generate():
        """Auto-generate exhibits from evidence grouped by category."""
        # Clear existing exhibits
        Exhibit.query.delete()

        # Group evidence by category (excluding cooperation which goes last)
        cat_order = [
            "parental_alienation", "verbal_abuse", "false_accusations",
            "communication_interference", "gatekeeping", "withholding",
            "emotional_manipulation", "schedule_violations", "impact_on_child",
            "financial_abuse", "third_party_witness", "documentation_of_cooperation",
        ]

        letter_idx = 0
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

        for cat_key in cat_order:
            items = EvidenceItem.query.filter_by(category=cat_key)\
                .order_by(EvidenceItem.event_date.asc()).all()
            if not items:
                continue

            cat_info = EVIDENCE_CATEGORIES.get(cat_key, {})
            letter = letters[letter_idx] if letter_idx < 26 else f"A{letter_idx - 25}"

            # Build narrative
            date_start = items[0].event_date
            date_end = items[-1].event_date
            child_count = sum(1 for i in items if i.child_present)
            sev_4_5 = sum(1 for i in items if i.severity >= 4)
            max_sev = max(i.severity for i in items)

            # Collect key quotes across all items (top 5 by severity)
            top_items = sorted(items, key=lambda x: x.severity, reverse=True)[:5]
            key_quotes = []
            for ti in top_items:
                for q in ti.quote_list[:1]:
                    key_quotes.append(q)

            narrative_parts = [
                f"Exhibit {letter} documents {len(items)} incidents of {cat_info.get('label', cat_key)} "
                f"spanning {date_start.strftime('%B %d, %Y')} through {date_end.strftime('%B %d, %Y')}.",
            ]

            if sev_4_5 > 0:
                narrative_parts.append(
                    f"{sev_4_5} of these incidents were rated severity 4 or 5 (serious to safety-level)."
                )
            if child_count > 0:
                narrative_parts.append(
                    f"The child was present or directly affected in {child_count} of these incidents."
                )

            # Evidence type breakdown
            type_counts = {}
            for i in items:
                t = EVIDENCE_TYPES.get(i.evidence_type, {}).get("label", i.evidence_type)
                type_counts[t] = type_counts.get(t, 0) + 1
            type_summary = ", ".join(f"{v} {k}{'s' if v > 1 else ''}" for k, v in type_counts.items())
            narrative_parts.append(f"Evidence sources: {type_summary}.")

            if key_quotes:
                narrative_parts.append("\nKey statements from the evidence:")
                for q in key_quotes[:4]:
                    narrative_parts.append(f'  - "{q}"')

            exhibit = Exhibit(
                letter=letter,
                title=f"Exhibit {letter}: {cat_info.get('label', cat_key)}",
                category=cat_key,
                narrative="\n".join(narrative_parts),
                evidence_ids=json.dumps([i.id for i in items]),
                date_range_start=date_start,
                date_range_end=date_end,
                incident_count=len(items),
                child_present_count=child_count,
                max_severity=max_sev,
                sort_order=letter_idx,
            )
            db.session.add(exhibit)
            letter_idx += 1

        db.session.commit()
        flash(f"Generated {letter_idx} exhibits from evidence.", "success")
        return redirect(url_for("exhibits_list"))

    @app.route("/exhibits/<int:exhibit_id>")
    def exhibit_detail(exhibit_id):
        exhibit = Exhibit.query.get_or_404(exhibit_id)
        evidence = EvidenceItem.query.filter(
            EvidenceItem.id.in_(exhibit.evidence_id_list)
        ).order_by(EvidenceItem.event_date.asc()).all()
        return render_template("exhibit_detail.html", exhibit=exhibit, evidence=evidence)

    @app.route("/exhibits/<int:exhibit_id>/edit", methods=["GET", "POST"])
    def exhibit_edit(exhibit_id):
        exhibit = Exhibit.query.get_or_404(exhibit_id)
        if request.method == "POST":
            exhibit.title = request.form.get("title", exhibit.title)
            exhibit.narrative = request.form.get("narrative", "").strip() or None
            evidence_ids = request.form.getlist("evidence_ids")
            exhibit.evidence_ids = json.dumps([int(x) for x in evidence_ids]) if evidence_ids else "[]"

            # Recalculate stats
            items = EvidenceItem.query.filter(EvidenceItem.id.in_([int(x) for x in evidence_ids])).all()
            if items:
                exhibit.incident_count = len(items)
                exhibit.child_present_count = sum(1 for i in items if i.child_present)
                exhibit.max_severity = max(i.severity for i in items)
                dates = [i.event_date for i in items]
                exhibit.date_range_start = min(dates)
                exhibit.date_range_end = max(dates)

            db.session.commit()
            flash(f"Exhibit {exhibit.letter} updated.", "success")
            return redirect(url_for("exhibit_detail", exhibit_id=exhibit.id))

        all_items = EvidenceItem.query.order_by(EvidenceItem.event_date.asc()).all()
        return render_template("exhibit_edit.html", exhibit=exhibit, all_items=all_items)

    @app.route("/print/exhibit/<int:exhibit_id>")
    def print_exhibit(exhibit_id):
        exhibit = Exhibit.query.get_or_404(exhibit_id)
        evidence = EvidenceItem.query.filter(
            EvidenceItem.id.in_(exhibit.evidence_id_list)
        ).order_by(EvidenceItem.event_date.asc()).all()
        return render_template("print_exhibit.html", exhibit=exhibit, evidence=evidence)

    @app.route("/print/exhibits")
    def print_all_exhibits():
        exhibits = Exhibit.query.order_by(Exhibit.sort_order.asc()).all()
        exhibit_data = []
        for exhibit in exhibits:
            evidence = EvidenceItem.query.filter(
                EvidenceItem.id.in_(exhibit.evidence_id_list)
            ).order_by(EvidenceItem.event_date.asc()).all()
            exhibit_data.append({"exhibit": exhibit, "evidence": evidence})
        return render_template("print_all_exhibits.html", exhibit_data=exhibit_data)

    # -- Feature Suggestions --

    @app.route("/suggestions")
    def suggestions_list():
        status_filter = request.args.get("status", "open")
        if status_filter == "all":
            suggestions = FeatureSuggestion.query.order_by(FeatureSuggestion.created_at.desc()).all()
        else:
            suggestions = FeatureSuggestion.query.filter_by(status=status_filter)\
                .order_by(FeatureSuggestion.created_at.desc()).all()
        counts = {
            "open": FeatureSuggestion.query.filter_by(status="open").count(),
            "completed": FeatureSuggestion.query.filter_by(status="completed").count(),
            "removed": FeatureSuggestion.query.filter_by(status="removed").count(),
        }
        return render_template("suggestions.html", suggestions=suggestions,
                               status_filter=status_filter, counts=counts)

    @app.route("/suggestions/add", methods=["POST"])
    def suggestion_add():
        text = request.form.get("text", "").strip()
        if text:
            s = FeatureSuggestion(text=text)
            db.session.add(s)
            db.session.commit()
            flash("Feature suggestion added!", "success")
        return redirect(request.referrer or url_for("suggestions_list"))

    @app.route("/suggestions/<int:sid>/complete", methods=["POST"])
    def suggestion_complete(sid):
        s = FeatureSuggestion.query.get_or_404(sid)
        s.status = "completed"
        s.completed_at = datetime.utcnow()
        db.session.commit()
        flash(f"Marked as completed: {s.text[:50]}", "success")
        return redirect(request.referrer or url_for("suggestions_list"))

    @app.route("/suggestions/<int:sid>/remove", methods=["POST"])
    def suggestion_remove(sid):
        s = FeatureSuggestion.query.get_or_404(sid)
        s.status = "removed"
        db.session.commit()
        flash(f"Removed: {s.text[:50]}", "success")
        return redirect(request.referrer or url_for("suggestions_list"))

    @app.route("/suggestions/<int:sid>/reopen", methods=["POST"])
    def suggestion_reopen(sid):
        s = FeatureSuggestion.query.get_or_404(sid)
        s.status = "open"
        s.completed_at = None
        db.session.commit()
        return redirect(request.referrer or url_for("suggestions_list"))

    # -- Listening Station --

    @app.route("/listen")
    def listen():
        category_filter = request.args.get("category")
        query = EvidenceItem.query.filter(
            EvidenceItem.evidence_type.in_(["audio", "voicemail"]),
            EvidenceItem.file_path.isnot(None),
        )
        if category_filter:
            query = query.filter(EvidenceItem.category == category_filter)
        items = query.order_by(EvidenceItem.event_date.asc()).all()

        # Attach notes to each item
        recordings = []
        for item in items:
            notes = RecordingNote.query.filter_by(evidence_id=item.id)\
                .order_by(RecordingNote.timestamp_seconds.asc()).all()
            recordings.append({"item": item, "notes": notes})
        return render_template("listen.html", recordings=recordings,
                               category_filter=category_filter)

    @app.route("/listen/<int:item_id>/note", methods=["POST"])
    def listen_add_note(item_id):
        item = EvidenceItem.query.get_or_404(item_id)
        content = request.form.get("content", "").strip()
        if not content:
            return jsonify({"error": "Note content required"}), 400

        ts_str = request.form.get("timestamp", "0")
        try:
            # Accept MM:SS or raw seconds
            if ":" in ts_str:
                parts = ts_str.split(":")
                ts_seconds = float(parts[0]) * 60 + float(parts[1])
            else:
                ts_seconds = float(ts_str)
        except (ValueError, IndexError):
            ts_seconds = 0

        note_type = request.form.get("note_type", "note")

        note = RecordingNote(
            evidence_id=item.id,
            timestamp_seconds=ts_seconds,
            note_type=note_type,
            content=content,
        )
        db.session.add(note)
        db.session.commit()

        return jsonify({
            "id": note.id,
            "evidence_id": note.evidence_id,
            "timestamp": note.timestamp_formatted,
            "timestamp_seconds": note.timestamp_seconds,
            "note_type": note.note_type,
            "content": note.content,
            "recording_title": item.title,
            "created_at": note.created_at.strftime("%Y-%m-%d %I:%M %p"),
        })

    @app.route("/listen/note/<int:note_id>/delete", methods=["POST"])
    def listen_delete_note(note_id):
        note = RecordingNote.query.get_or_404(note_id)
        db.session.delete(note)
        db.session.commit()
        return jsonify({"ok": True})

    @app.route("/listen/export")
    def listen_export():
        """Export all recording notes as CSV."""
        import csv
        import io

        notes = RecordingNote.query.order_by(
            RecordingNote.evidence_id.asc(),
            RecordingNote.timestamp_seconds.asc(),
        ).all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Recording Title", "Recording Date", "Category",
                         "Timestamp", "Note Type", "Note", "Created At"])
        for note in notes:
            item = note.evidence
            writer.writerow([
                item.title,
                item.event_date.strftime("%Y-%m-%d %I:%M %p"),
                EVIDENCE_CATEGORIES.get(item.category, {}).get("label", item.category),
                note.timestamp_formatted,
                note.note_type,
                note.content,
                note.created_at.strftime("%Y-%m-%d %I:%M %p"),
            ])

        csv_data = output.getvalue()
        return Response(
            csv_data,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename=recording_notes_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"},
        )

    # -- AI Counsel --

    @app.route("/counsel")
    def counsel():
        conversations = Conversation.query.order_by(Conversation.updated_at.desc()).all()
        active_id = request.args.get("conversation_id", type=int)
        active_convo = None
        messages = []
        if active_id:
            active_convo = Conversation.query.get(active_id)
            if active_convo:
                messages = active_convo.messages
        return render_template("counsel.html",
                               conversations=conversations,
                               active_convo=active_convo,
                               messages=messages)

    @app.route("/counsel/new", methods=["POST"])
    def counsel_new():
        mode = request.form.get("mode", "general")
        convo = Conversation(
            title="New Conversation",
            mode=mode,
        )
        db.session.add(convo)
        db.session.commit()
        return redirect(url_for("counsel", conversation_id=convo.id))

    @app.route("/counsel/<int:convo_id>/delete", methods=["POST"])
    def counsel_delete(convo_id):
        convo = Conversation.query.get_or_404(convo_id)
        Message.query.filter_by(conversation_id=convo.id).delete()
        db.session.delete(convo)
        db.session.commit()
        flash("Conversation deleted.", "success")
        return redirect(url_for("counsel"))

    @app.route("/counsel/<int:convo_id>/ask", methods=["POST"])
    def counsel_ask(convo_id):
        convo = Conversation.query.get_or_404(convo_id)
        user_input = request.form.get("message", "").strip()
        if not user_input:
            return redirect(url_for("counsel", conversation_id=convo.id))

        # Save user message
        user_msg = Message(conversation_id=convo.id, role="user", content=user_input)
        db.session.add(user_msg)

        # Auto-title from first message
        if convo.title == "New Conversation":
            convo.title = user_input[:80] + ("..." if len(user_input) > 80 else "")

        db.session.commit()

        # Build messages for Claude
        client = get_anthropic_client()
        if not client:
            error_msg = Message(
                conversation_id=convo.id,
                role="assistant",
                content="API key not configured. Set ANTHROPIC_API_KEY environment variable.",
            )
            db.session.add(error_msg)
            db.session.commit()
            return redirect(url_for("counsel", conversation_id=convo.id))

        # Build knowledge base context
        kb = build_knowledge_base()

        # Build conversation history
        api_messages = []
        for msg in convo.messages:
            api_messages.append({"role": msg.role, "content": msg.content})

        # Mode-specific system prompt additions
        mode_prompts = {
            "exhibit": "\n\nThe user wants to generate court exhibits. Draft formal exhibit narratives with proper legal formatting. Include evidence item references, date ranges, severity analysis, and child-presence flags.",
            "pattern": "\n\nThe user wants to identify patterns of behavior. Look for repeated incidents across time, escalating severity, and corroborating evidence across categories.",
            "timeline": "\n\nThe user wants timeline analysis. Focus on chronological patterns, frequency of incidents, gaps in documentation, and how events relate to each other over time.",
        }
        mode_addition = mode_prompts.get(convo.mode, "")

        system = f"{COUNSEL_SYSTEM_PROMPT}{mode_addition}\n\n{kb}"

        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=4096,
                system=system,
                messages=api_messages,
            )
            assistant_text = response.content[0].text
        except Exception as e:
            assistant_text = f"Error communicating with Claude: {str(e)}"

        assistant_msg = Message(
            conversation_id=convo.id,
            role="assistant",
            content=assistant_text,
        )
        db.session.add(assistant_msg)
        convo.updated_at = datetime.utcnow()
        db.session.commit()

        return redirect(url_for("counsel", conversation_id=convo.id))

    @app.route("/counsel/<int:convo_id>/stream", methods=["POST"])
    def counsel_stream(convo_id):
        """Stream Claude's response via Server-Sent Events."""
        convo = Conversation.query.get_or_404(convo_id)
        user_input = request.form.get("message", "").strip()
        if not user_input:
            return jsonify({"error": "Empty message"}), 400

        # Save user message
        user_msg = Message(conversation_id=convo.id, role="user", content=user_input)
        db.session.add(user_msg)
        if convo.title == "New Conversation":
            convo.title = user_input[:80] + ("..." if len(user_input) > 80 else "")
        db.session.commit()

        client = get_anthropic_client()
        if not client:
            return jsonify({"error": "API key not configured"}), 500

        kb = build_knowledge_base()
        api_messages = []
        for msg in convo.messages:
            api_messages.append({"role": msg.role, "content": msg.content})

        mode_prompts = {
            "exhibit": "\n\nThe user wants to generate court exhibits. Draft formal exhibit narratives with proper legal formatting. Include evidence item references, date ranges, severity analysis, and child-presence flags.",
            "pattern": "\n\nThe user wants to identify patterns of behavior. Look for repeated incidents across time, escalating severity, and corroborating evidence across categories.",
            "timeline": "\n\nThe user wants timeline analysis. Focus on chronological patterns, frequency of incidents, gaps in documentation, and how events relate to each other over time.",
        }
        mode_addition = mode_prompts.get(convo.mode, "")
        system = f"{COUNSEL_SYSTEM_PROMPT}{mode_addition}\n\n{kb}"

        def generate():
            full_response = []
            try:
                with client.messages.stream(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=4096,
                    system=system,
                    messages=api_messages,
                ) as stream:
                    for text in stream.text_stream:
                        full_response.append(text)
                        yield f"data: {json.dumps({'text': text})}\n\n"
            except Exception as e:
                error_text = f"Error: {str(e)}"
                full_response.append(error_text)
                yield f"data: {json.dumps({'text': error_text})}\n\n"

            # Save complete response
            with app.app_context():
                assistant_msg = Message(
                    conversation_id=convo.id,
                    role="assistant",
                    content="".join(full_response),
                )
                db.session.add(assistant_msg)
                convo.updated_at = datetime.utcnow()
                db.session.commit()

            yield f"data: {json.dumps({'done': True})}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.route("/api/knowledge-base")
    def api_knowledge_base():
        """Return the knowledge base as JSON for debugging/export."""
        kb = build_knowledge_base()
        return jsonify({
            "knowledge_base": kb,
            "char_count": len(kb),
            "evidence_count": EvidenceItem.query.count(),
        })

    return app


# Module-level app for gunicorn: gunicorn app:app
app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5050)
