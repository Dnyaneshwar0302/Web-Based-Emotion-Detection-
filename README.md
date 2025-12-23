# Emotion Tracker Web App

A full-stack face emotion recognition and weekly reporting project:

- Login / signup system (multi-user)
- Live webcam-based facial emotion detection using DeepFace
- Logs emotions with timestamps
- Weekly emotion summaries
- Goal-setting form per week
- Recommendation for next week based on previous week's emotions
- Export weekly report as a PDF

## How to run

1. **Create and activate a virtual environment (recommended)**

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. **Install dependencies**

```bash
pip install -r requirements.txt
```

3. **Run the app**

```bash
export FLASK_APP=app.py  # On Windows: set FLASK_APP=app.py
flask run
```

4. Open the browser at `http://127.0.0.1:5000`

> Note: The first time you run emotion detection, DeepFace will download model weights automatically.
> Make sure you have a good internet connection for that step.

## Folder structure

- `app.py` – main Flask app
- `models.py` – database models (User, EmotionLog, WeeklyGoal)
- `report_generator.py` – PDF report generation
- `config.py` – configuration & database URL
- `templates/` – HTML templates (Jinja2)
- `static/css/main.css` – custom styling
- `static/js/main.js` – frontend logic (camera, API calls)
- `requirements.txt` – Python dependencies

## Notes

- Emotions are detected on a timer (every 5 seconds) while tracking is enabled.
- Each detection is saved with a UTC timestamp.
- Weekly report uses Monday–Sunday as the week range.
- PDF reports can be downloaded from the dashboard.
