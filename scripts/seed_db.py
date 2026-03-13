"""Seed the database from seed_data.json on every deploy."""
import json
import os
from datetime import datetime


def seed():
    from app import create_app, db, EvidenceItem, FeatureSuggestion

    app = create_app()
    seed_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "seed_data.json")

    if not os.path.exists(seed_path):
        print("seed_data.json not found, skipping seed.")
        return

    with app.app_context():
        # Skip if already seeded
        if EvidenceItem.query.count() > 0:
            print(f"Database already has {EvidenceItem.query.count()} items, skipping seed.")
            return

        with open(seed_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Import evidence items
        for item_data in data.get("evidence_items", []):
            item = EvidenceItem(
                title=item_data["title"],
                description=item_data.get("description"),
                evidence_type=item_data["evidence_type"],
                category=item_data["category"],
                subcategories=item_data.get("subcategories"),
                event_date=datetime.fromisoformat(item_data["event_date"]) if item_data.get("event_date") else datetime.utcnow(),
                file_path=item_data.get("file_path"),
                transcript=item_data.get("transcript"),
                raw_text=item_data.get("raw_text"),
                key_quotes=item_data.get("key_quotes"),
                severity=item_data.get("severity", 3),
                people_present=item_data.get("people_present"),
                child_present=item_data.get("child_present", False),
                notes=item_data.get("notes"),
                tags=item_data.get("tags"),
                created_at=datetime.fromisoformat(item_data["created_at"]) if item_data.get("created_at") else datetime.utcnow(),
                updated_at=datetime.fromisoformat(item_data["updated_at"]) if item_data.get("updated_at") else datetime.utcnow(),
            )
            db.session.add(item)

        # Import feature suggestions
        for sug_data in data.get("feature_suggestions", []):
            completed_at = None
            if sug_data.get("completed_at"):
                completed_at = datetime.fromisoformat(sug_data["completed_at"])
            sug = FeatureSuggestion(
                text=sug_data["text"],
                status=sug_data.get("status", "open"),
                created_at=datetime.fromisoformat(sug_data["created_at"]) if sug_data.get("created_at") else datetime.utcnow(),
                completed_at=completed_at,
            )
            db.session.add(sug)

        db.session.commit()
        print(f"Seeded {len(data.get('evidence_items', []))} evidence items and {len(data.get('feature_suggestions', []))} suggestions.")


if __name__ == "__main__":
    seed()
