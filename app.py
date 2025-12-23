import os
import warnings

# -----------------------------
# 🔇 Disable TensorFlow / Deprecation Warnings
# -----------------------------
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message="pkg_resources is deprecated as an API")

# -----------------------------
# Normal Imports
# -----------------------------
import base64
import io
import logging
from datetime import datetime, timedelta, date, timezone
from typing import Optional, Tuple

import cv2
import numpy as np
from fer.fer import FER
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, jsonify, session, send_file
)
from flask_login import (
    LoginManager, login_user, login_required,
    logout_user, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash

from config import Config
from models import db, User, EmotionLog, WeeklyGoal
from report_generator import generate_weekly_report_pdf


# -----------------------------
# App Setup
# -----------------------------
app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("emotion-tracker")

# -----------------------------
# User Loader
# -----------------------------
@login_manager.user_loader
def load_user(user_id: str) -> Optional[User]:
    return User.query.get(int(user_id))


# -----------------------------
# Create DB if not exists
# -----------------------------
with app.app_context():
    db.create_all()


# -----------------------------
# Load FER Model (Single Instance)
# -----------------------------
_fer_model = None


def load_emotion_model_once():
    global _fer_model
    if _fer_model is None:
        _fer_model = FER(mtcnn=True)
        logger.info("FER model loaded successfully")
    return _fer_model


@app.before_request
def ensure_models_loaded():
    if request.path.startswith("/api/detect_emotion"):
        load_emotion_model_once()


# -----------------------------
# Utility: Decode Image
# -----------------------------
def decode_base64_image(data_url: str) -> np.ndarray:
    if "," in data_url:
        encoded = data_url.split(",")[1]
    else:
        encoded = data_url
    img_bytes = base64.b64decode(encoded)
    nparr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)  # BGR
    return img


# -----------------------------
# Detect Emotion (FER)
# -----------------------------
@app.route("/api/detect_emotion", methods=["POST"])
def detect_emotion():
    try:
        data = request.get_json(force=True)
        img_data = data.get("image")

        if not img_data:
            return jsonify({"error": "No image received"}), 400

        img = decode_base64_image(img_data)
        fer = load_emotion_model_once()

        faces = fer.detect_emotions(img)
        ts = datetime.now(timezone.utc)

        if not faces:
            return jsonify({
                "timestamp": ts.isoformat(),
                "emotion": None,
                "confidence": None,
                "message": "No face detected"
            }), 200

        emotions = faces[0]["emotions"]
        dominant = max(emotions, key=emotions.get)
        confidence = float(emotions[dominant])
        dominant = dominant.lower()

        # Save to DB
        try:
            emo_log = EmotionLog(
                user_id=current_user.id if current_user.is_authenticated else None,
                emotion=dominant,
                confidence=confidence,
                timestamp=ts
            )
            db.session.add(emo_log)
            db.session.commit()
        except Exception as e:
            logger.error("DB save failed: %s", e)
            db.session.rollback()

        return jsonify({
            "timestamp": ts.isoformat(),
            "emotion": dominant,
            "confidence": confidence
        })

    except Exception as e:
        logger.error("detect_emotion error: %s", e)
        return jsonify({"error": "Server error"}), 500


# -----------------------------
# Summary (Last 2 Minutes)
# -----------------------------
@app.route("/api/summary_2min")
@login_required
def summary_2min():
    try:
        now = datetime.now(timezone.utc)
        two_min = now - timedelta(seconds=120)

        logs = EmotionLog.query.filter(
            EmotionLog.user_id == current_user.id,
            EmotionLog.timestamp >= two_min
        ).all()

        if not logs:
            return jsonify({"total": 0, "summary": []})

        from collections import Counter

        emotions = [log.emotion for log in logs]
        total = len(emotions)
        counts = Counter(emotions)

        summary = [{
            "emotion": emo,
            "count": cnt,
            "percentage": (cnt / total) * 100
        } for emo, cnt in counts.items()]

        summary.sort(key=lambda x: x["count"], reverse=True)

        return jsonify({"total": total, "summary": summary})

    except Exception:
        return jsonify({"error": "Internal error"}), 500


# -----------------------------
# Save Dashboard Summary (For PDF)
# -----------------------------
@app.route("/api/save_dashboard_summary", methods=["POST"])
@login_required
def save_dashboard_summary():
    data = request.get_json(force=True)
    summary = data.get("summary")

    session["latest_dashboard_summary"] = summary
    return jsonify({"message": "Summary saved"})


# -----------------------------
# Recommendation Helper FIXED
# -----------------------------
def get_last_emotion():
    """Return the latest saved emotion for the current user."""
    try:
        latest = EmotionLog.query.filter_by(
            user_id=current_user.id
        ).order_by(EmotionLog.timestamp.desc()).first()

        if latest:
            return latest.emotion

        return None
    except Exception as e:
        logger.error("Failed to fetch last emotion: %s", e)
        return None

def build_recommendation(logs, goal=None):
    """Used ONLY for PDF report generation."""

    if not logs:
        return "No emotion data available."

    # 1. Find dominant emotion from logs (same as summary)
    from collections import Counter
    emotions = [log.emotion.lower() for log in logs]
    dominant = Counter(emotions).most_common(1)[0][0]

    # 2. Weekly goal
    target = goal.target_emotion.lower() if goal else None

    # 3. Suggestion list
    suggestions = {
        "happy": [
            "Write down 3 things you're grateful for.",
            "Share positivity by messaging someone you appreciate.",
            "Do a quick joyful activity like dancing or listening to music."
        ],
        "sad": [
            "Talk to a friend or someone you trust.",
            "Write your emotions in a journal.",
            "Watch something uplifting or calming."
        ],
        "angry": [
            "Take 5–10 deep breaths slowly.",
            "Go for a short walk to release frustration.",
            "Step away from the situation temporarily."
        ],
        "fear": [
            "Practice slow breathing for 60 seconds.",
            "Remind yourself what is under your control.",
            "Talk to someone supportive to reduce anxiety."
        ],
        "neutral": [
            "Take a short mindful walk.",
            "Drink water and stretch your body.",
            "Plan the next task with clarity."
        ],
        "surprise": [
            "Pause and take a moment to process the situation.",
            "Identify whether the surprise is good or bad.",
            "Write down how this surprise may affect your goals."
        ]
    }

    # 4. Format suggestions
    if dominant in suggestions:
        bullet_points = "\n• " + "\n• ".join(suggestions[dominant])
    else:
        bullet_points = "\n• No suggestions available."

    # 5. Build final recommendation text (PDF-friendly)
    if target:
        if dominant == target:
            return (
                f"Your dominant emotion for this period was {dominant}, "
                f"which aligns well with your weekly goal ({target}).\n"
                f"Recommended actions to maintain this positive state:{bullet_points}"
            )
        else:
            return (
                f"Your dominant emotion for this period was {dominant}, "
                f"which does not fully match your weekly goal ({target}).\n"
                f"Here are some helpful activities:{bullet_points}"
            )

    return (
        f"Your dominant emotion for this period was {dominant}.\n"
        f"Suggested actions:{bullet_points}"
    )

# -----------------------------
# Recommendation API (Uses your multi-suggestion list)
# -----------------------------
@app.route("/api/recommendation")
@login_required
def recommendation():

    # STEP 1 — Get last 2 minutes logs
    now = datetime.now(timezone.utc)
    two_min = now - timedelta(seconds=120)

    logs = EmotionLog.query.filter(
        EmotionLog.user_id == current_user.id,
        EmotionLog.timestamp >= two_min
    ).all()

    if not logs:
        return {"recommendation": "No emotion data found in the last 2 minutes."}

    # STEP 2 — Count emotions
    from collections import Counter
    emotions_list = [log.emotion.lower() for log in logs]
    dominant = Counter(emotions_list).most_common(1)[0][0]

    # STEP 3 — Suggestion list
    suggestions = {
        "happy": [
            "Write down 3 things you're grateful for.",
            "Share positivity by messaging someone you appreciate.",
            "Do a quick joyful activity like dancing or listening to music."
        ],
        "sad": [
            "Talk to a friend or someone you trust.",
            "Write your emotions in a journal.",
            "Watch something uplifting or calming."
        ],
        "angry": [
            "Take 5–10 deep breaths slowly.",
            "Go for a short walk to release frustration.",
            "Step away from the situation temporarily."
        ],
        "fear": [
            "Practice slow breathing for 60 seconds.",
            "Remind yourself what is under your control.",
            "Talk to someone supportive to reduce anxiety."
        ],
        "neutral": [
            "Take a short mindful walk.",
            "Drink water and stretch your body.",
            "Plan the next task with clarity."
        ],
        "surprise": [
            "Pause and take a moment to process the situation.",
            "Identify whether the surprise is good or bad.",
            "Write down how this surprise may affect your goals."
        ]
    }

    if dominant not in suggestions:
        return {"recommendation": f"No suggestions available for {dominant}."}

    # STEP 4 — Format output
    all_suggestions = "\n• " + "\n• ".join(suggestions[dominant])

    return {
        "recommendation": f"Based on the last 2 minutes, the dominant emotion is {dominant}.\nHere are your suggestions:{all_suggestions}"
    }



# -----------------------------
# Dashboard Page
# -----------------------------
@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/dashboard")
@login_required
def dashboard():
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    goal = WeeklyGoal.query.filter_by(
        user_id=current_user.id,
        week_start=week_start
    ).first()

    return render_template("dashboard.html",
                           week_start=week_start,
                           week_end=week_end,
                           goal=goal)


# -----------------------------
# PDF Report
# -----------------------------
@app.route("/report/pdf")
@login_required
def report_pdf():
    try:
        now = datetime.now(timezone.utc)
        two_min = now - timedelta(seconds=120)

        logs = EmotionLog.query.filter(
            EmotionLog.user_id == current_user.id,
            EmotionLog.timestamp >= two_min
        ).order_by(EmotionLog.timestamp.desc()).all()

        if not logs:
            return jsonify({"error": "No logs available to generate report."}), 400

        goal = WeeklyGoal.query.filter_by(user_id=current_user.id).order_by(
            WeeklyGoal.week_start.desc()
        ).first()

        recommendation = build_recommendation(logs, goal)

        pdf_buffer = generate_weekly_report_pdf(
            current_user, logs, None, None, goal, recommendation
        )

        pdf_buffer.seek(0)
        return send_file(
            pdf_buffer,
            as_attachment=True,
            download_name="emotion_report.pdf",
            mimetype="application/pdf"
        )

    except Exception as e:
        logger.exception("PDF error")
        return jsonify({"error": "Report error", "details": str(e)}), 500



# -----------------------------
# Auth Routes
# -----------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password")

        if User.query.filter_by(email=email).first():
            flash("Email already exists", "danger")
            return redirect(url_for("register"))

        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password)
        )
        db.session.add(user)
        db.session.commit()

        flash("Registration successful", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password").strip()

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for("dashboard"))

        flash("Invalid credentials", "danger")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("logout_popup"))


@app.route("/logout_popup")
def logout_popup():
    return render_template("logout_popup.html")


# -----------------------------
# Run App
# -----------------------------
if __name__ == "__main__":
    app.run(debug=True)
