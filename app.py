import os
import json
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix

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


# ---------------------------------------------------------------------------
# App Factory
# ---------------------------------------------------------------------------
def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "evidence-dev-key-change-in-prod")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///evidence.db"
    app.config["UPLOAD_FOLDER"] = os.path.join(os.path.dirname(__file__), "uploads")
    app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500MB for video/audio

    # URL prefix for reverse proxy (e.g. kingdombuilders.ai/evidence)
    url_prefix = os.environ.get("URL_PREFIX", "")
    if url_prefix:
        app.config["APPLICATION_ROOT"] = url_prefix
        from werkzeug.middleware.dispatcher import DispatcherMiddleware
        app.wsgi_app = DispatcherMiddleware(
            Flask(__name__), {url_prefix: app}
        )

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
        }

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
        q = request.args.get("q", "").strip()
        results = []
        if q:
            like = f"%{q}%"
            results = EvidenceItem.query.filter(
                db.or_(
                    EvidenceItem.title.ilike(like),
                    EvidenceItem.description.ilike(like),
                    EvidenceItem.raw_text.ilike(like),
                    EvidenceItem.transcript.ilike(like),
                    EvidenceItem.key_quotes.ilike(like),
                    EvidenceItem.notes.ilike(like),
                    EvidenceItem.tags.ilike(like),
                )
            ).order_by(EvidenceItem.event_date.asc()).all()
        return render_template("search.html", q=q, results=results)

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

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5050)
