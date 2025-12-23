let video = null;
let canvas = null;
let context = null;
let trackingInterval = null;
let autoStopTimer = null;

// 🔥 Caches
let lastSummaryCache = null;
let lastRecommendationCache = null;

// Keep track of last shown timestamp to avoid duplicate UI updates
let _lastShownTimestamp = null;

const CAPTURE_INTERVAL_MS = 5000; // 5 seconds
const AUTO_STOP_MS = 2 * 60 * 1000; // 2 minutes auto-stop

// ----------------------------------------------
// CAMERA SETUP
// ----------------------------------------------
async function setupCamera() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    alert("Camera is not supported in this browser.");
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: true });
    video.srcObject = stream;
    await video.play();
    document.getElementById("statusText").innerText =
      "Camera on, tracking stopped";
  } catch (err) {
    console.error(err);
    alert("Could not access camera: " + err.message);
  }
}

function stopWebcamStream() {
  if (video && video.srcObject) {
    video.srcObject.getTracks().forEach((track) => track.stop());
    video.srcObject = null;
  }
  document.getElementById("statusText").innerText =
    "Camera stopped automatically";
}

// ----------------------------------------------
// Helper: normalize backend response to single {emotion, confidence, timestamp}
// Handles cases where backend mistakenly returns multiple emotions or arrays.
function normalizeDetectionResponse(data) {
  // If backend sent an array of predictions, pick the one with max confidence
  if (Array.isArray(data)) {
    let best = null;
    for (const item of data) {
      if (!item) continue;
      if (!best || (item.confidence || 0) > (best.confidence || 0)) best = item;
    }
    return best || null;
  }

  // If backend returned an object that contains a `predictions` array
  if (data && Array.isArray(data.predictions)) {
    let best = null;
    for (const item of data.predictions) {
      if (!item) continue;
      if (!best || (item.confidence || 0) > (best.confidence || 0)) best = item;
    }
    return best || null;
  }

  // If it's a single object with fields, return it directly
  if (data && typeof data === "object") return data;

  return null;
}

// ----------------------------------------------
// CAPTURE FRAME + SEND
// ----------------------------------------------
function captureFrameAndSend() {
  try {
    if (!video || video.readyState !== 4) {
      // Not ready yet
      //console.debug("Video not ready:", video && video.readyState);
      return;
    }

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const dataUrl = canvas.toDataURL("image/jpeg");

    fetch("/api/detect_emotion", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image: dataUrl }),
    })
      .then((r) => r.json())
      .then((raw) => {
        if (!raw) {
          console.warn("Empty response from /api/detect_emotion");
          return;
        }
        if (raw.error) {
          console.warn("Backend error:", raw.error);
          return;
        }

        // Normalize response to a single record object
        const data = normalizeDetectionResponse(raw);
        if (!data) {
          console.warn("Could not normalize backend response:", raw);
          return;
        }

        // Validate fields and pick sensible defaults
        let emotion = data.emotion || data.label || data.prediction || null;
        let confidence = typeof data.confidence === "number" ? data.confidence : null;
        let timestamp = data.timestamp || new Date().toLocaleTimeString();

        // If backend returned confidence as percent (like 82 or 82.0), convert to 0-1
        if (confidence !== null && confidence > 1) {
          confidence = confidence / 100;
        }

        // Clamp confidence to [0,1] and fallback to null if invalid
        if (typeof confidence !== "number" || !isFinite(confidence)) {
          confidence = null;
        } else {
          confidence = Math.max(0, Math.min(1, confidence));
        }

        // If emotion is missing but predictions object exists, try to derive
        if (!emotion && Array.isArray(raw.predictions) && raw.predictions.length > 0) {
          const best = raw.predictions.reduce((a, b) => (b.confidence > a.confidence ? b : a));
          emotion = best.emotion || best.label || null;
          if (!confidence) confidence = best.confidence || null;
        }

        // If still missing emotion, bail
        if (!emotion) {
          console.warn("No emotion label in detection response:", raw);
          return;
        }

        // Avoid updating UI repeatedly for same timestamp (debounce duplicate server logs)
        if (timestamp === _lastShownTimestamp) {
          // But still update confidence if it changed
          const currentConfText = document.getElementById("currentConfidence").innerText || "";
          const newConfText = confidence !== null ? `Confidence: ${(confidence * 100).toFixed(1)}%` : "";
          if (currentConfText !== newConfText) {
            document.getElementById("currentConfidence").innerText = newConfText;
          }
          return;
        }

        // Update last shown timestamp
        _lastShownTimestamp = timestamp;

        // Update DOM safely
        try {
          document.getElementById("currentEmotion").innerText = emotion.toString().toUpperCase();
        } catch (e) {
          console.error("Error updating currentEmotion:", e);
        }

        document.getElementById("currentConfidence").innerText = confidence !== null
          ? `Confidence: ${(confidence * 100).toFixed(1)}%`
          : "";

        document.getElementById("currentTimestamp").innerText = `Logged at: ${timestamp}`;

        // Trigger summary refresh (updateCache = true)
        try {
          refreshSummary(true);
        } catch (e) {
          console.error("Error refreshing summary after capture:", e);
        }
      })
      .catch((err) => {
        console.error("fetch /api/detect_emotion failed:", err);
      });
  } catch (err) {
    console.error("captureFrameAndSend error:", err);
  }
}

// ----------------------------------------------
// START / STOP TRACKING (FIXED VERSION)
// ----------------------------------------------
function startTracking() {
  if (trackingInterval) return;

  document.getElementById("statusText").innerText =
    "Tracking emotions every 5 seconds...";

  // ✔ FIX: Capture once immediately for UI update only
  setTimeout(() => {
    captureFrameAndSend();
  }, 500);

  // ✔ Continue capturing every 5 seconds
  trackingInterval = setInterval(captureFrameAndSend, CAPTURE_INTERVAL_MS);

  // Auto stop after 2 minutes
  autoStopTimer = setTimeout(() => {
    stopTracking();
    stopWebcamStream();
    alert("Tracking automatically stopped after 2 minutes.");
  }, AUTO_STOP_MS);
}

function stopTracking() {
  if (trackingInterval) {
    clearInterval(trackingInterval);
    trackingInterval = null;
  }
  if (autoStopTimer) {
    clearTimeout(autoStopTimer);
    autoStopTimer = null;
  }
  document.getElementById("statusText").innerText = "Tracking stopped";
}

// ----------------------------------------------
// SUMMARY (2 MINUTES)
function refreshSummary(updateCache = false) {
  fetch("/api/summary_2min")
    .then((r) => r.json())
    .then((data) => {
      const list = document.getElementById("weeklySummaryList");
      list.innerHTML = "";

      if (!data.summary || data.summary.length === 0) {
        list.innerHTML = `<li class="list-group-item text-muted">No data yet.</li>`;
        return;
      }

      fetch("/api/save_dashboard_summary", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ summary: data.summary })
      });

      if (updateCache) lastSummaryCache = data.summary;

      data.summary
        .filter(item => item.emotion !== "unknown")
        .forEach((item) => {
          const li = document.createElement("li");
          li.className =
            "list-group-item d-flex justify-content-between align-items-center";
          li.innerHTML = `
            <span>${item.emotion.toUpperCase()}</span>
            <span class="badge bg-primary rounded-pill">
              ${item.count} (${item.percentage.toFixed(1)}%)
            </span>
          `;
          list.appendChild(li);
        });

      refreshRecommendation(false);
    })
    .catch((err) => console.error(err));
}

// ----------------------------------------------
// RECOMMENDATION BUILDER
function buildRecommendationFromSummary(summary) {
  if (!summary || summary.length === 0)
    return "Not enough data collected in the last 2 minutes.";

  let total = 0;
  const counts = {};

  summary.forEach((item) => {
    counts[item.emotion] = (counts[item.emotion] || 0) + item.count;
    total += item.count;
  });

  let dominant = null;
  let domCount = 0;

  for (const [emo, cnt] of Object.entries(counts)) {
    if (cnt > domCount) {
      domCount = cnt;
      dominant = emo;
    }
  }

  const domPct = total ? (domCount / total) * 100 : 0;

  const positive = new Set(["happy", "surprise"]);
  const negative = new Set(["sad", "angry", "fear", "disgust"]);

  if (positive.has(dominant)) {
    return `Great job! Your dominant emotion was ${dominant} (${domPct.toFixed(
      1
    )}%). Stay positive!`;
  } else if (negative.has(dominant)) {
    return `Your dominant emotion was ${dominant} (${domPct.toFixed(
      1
    )}%). Try breathing exercises or a short break.`;
  } else {
    return `Your emotions were mostly ${dominant} (${domPct.toFixed(
      1
    )}%). Aim for emotional balance with small resets.`;
  }
}

// ----------------------------------------------
// RECOMMENDATION SYSTEM
function refreshRecommendation(forceServer = false) {
  const box = document.getElementById("recommendationBox");

  if (forceServer) {
    fetch("/api/recommendation")
      .then((r) => r.json())
      .then((data) => {
        lastRecommendationCache = data.recommendation;
        box.innerText = data.recommendation;
      })
      .catch((err) => console.error(err));
    return;
  }

  if (lastSummaryCache && lastSummaryCache.length > 0) {
    const rec = buildRecommendationFromSummary(lastSummaryCache);
    lastRecommendationCache = rec;
    box.innerText = rec;
    return;
  }

  if (lastRecommendationCache) {
    box.innerText = lastRecommendationCache;
    return;
  }

  fetch("/api/recommendation")
    .then((r) => r.json())
    .then((data) => {
      lastRecommendationCache = data.recommendation;
      box.innerText = data.recommendation;
    })
    .catch((err) => console.error(err));
}

// ----------------------------------------------
// GOAL FORM
function setupGoalForm() {
  const form = document.getElementById("goalForm");
  if (!form) return;

  form.addEventListener("submit", (e) => {
    e.preventDefault();

    const targetEmotion = document.getElementById("targetEmotionSelect").value;
    const notes = document.getElementById("goalNotes").value;

    fetch("/api/set_goal", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_emotion: targetEmotion, notes }),
    })
      .then((r) => r.json())
      .then(() => alert("Goal saved!"))
      .catch((err) => console.error(err));
  });
}

// ----------------------------------------------
// PAGE LOAD
document.addEventListener("DOMContentLoaded", () => {
  video = document.getElementById("video");
  canvas = document.getElementById("canvas");
  if (canvas) context = canvas.getContext("2d");

  if (video) setupCamera();

  document
    .getElementById("startTrackingBtn")
    ?.addEventListener("click", startTracking);

  document
    .getElementById("stopTrackingBtn")
    ?.addEventListener("click", () => {
      stopTracking();
      stopWebcamStream();
    });

  document
    .getElementById("refreshSummaryBtn")
    ?.addEventListener("click", () => refreshSummary(false));

  document
    .getElementById("refreshRecBtn")
    ?.addEventListener("click", () => refreshRecommendation(true));

  setupGoalForm();
  refreshSummary(false);
});
