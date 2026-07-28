"""
Distress Detection ML module.
Architecture:
  • Primary  — lightweight CNN trained on RAVDESS + CREMA-D emotion datasets (librosa features)
  • Fallback — rule-based energy/pitch heuristics (no model file required)

The model file path: app/ml/models/distress_model.pkl
If the model file is absent, the system transparently falls back to heuristics
so the app continues working during development / cold boot.
"""
import io
import logging
import os
from typing import Optional

import numpy as np

from app.config import settings

logger = logging.getLogger("safeher.ml.distress")

# Distress-indicative emotion labels across common speech datasets
DISTRESS_EMOTIONS = {"fear", "panic", "angry", "disgust", "sad", "crying", "distress"}
NEUTRAL_EMOTIONS = {"neutral", "calm", "happy", "surprise"}

# Path to serialised sklearn/torch model
MODEL_PATH = os.path.join(settings.ML_MODELS_DIR, "distress_model.pkl")

_model = None  # lazy-loaded


def _load_model():
    """Lazy-load the distress classifier once."""
    global _model
    if _model is not None:
        return _model
    try:
        import joblib
        if os.path.exists(MODEL_PATH):
            _model = joblib.load(MODEL_PATH)
            logger.info("Distress model loaded from %s", MODEL_PATH)
        else:
            logger.warning("Distress model not found at %s — using heuristic fallback", MODEL_PATH)
    except Exception as exc:
        logger.warning("Distress model load failed (%s) — using heuristics", exc)
    return _model


def _extract_features(audio_bytes: bytes) -> Optional[np.ndarray]:
    """
    Extract MFCC + chroma + spectral contrast features using librosa.
    Returns (1, n_features) ndarray or None on failure.
    """
    try:
        import librosa
        y, sr = librosa.load(io.BytesIO(audio_bytes), sr=22050, mono=True, duration=30.0)

        if len(y) < sr * 0.5:  # too short
            return None

        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=40)
        mfcc_stats = np.concatenate([mfcc.mean(axis=1), mfcc.std(axis=1)])  # 80

        chroma = librosa.feature.chroma_stft(y=y, sr=sr)
        chroma_stats = np.concatenate([chroma.mean(axis=1), chroma.std(axis=1)])  # 24

        contrast = librosa.feature.spectral_contrast(y=y, sr=sr)
        contrast_stats = contrast.mean(axis=1)  # 7

        zcr = librosa.feature.zero_crossing_rate(y)
        zcr_mean = zcr.mean()  # 1

        rmse = librosa.feature.rms(y=y)
        rmse_mean = rmse.mean()  # 1

        features = np.concatenate([mfcc_stats, chroma_stats, contrast_stats, [zcr_mean, rmse_mean]])
        return features.reshape(1, -1)

    except ImportError:
        logger.debug("librosa not installed — cannot extract audio features")
        return None
    except Exception as exc:
        logger.error("Feature extraction failed: %s", exc)
        return None


def _heuristic_distress(audio_bytes: bytes) -> dict:
    """
    Energy and pitch-based heuristic distress detection.
    Used when no model is available or librosa is missing.
    """
    try:
        import librosa
        y, sr = librosa.load(io.BytesIO(audio_bytes), sr=22050, mono=True, duration=30.0)
        if len(y) == 0:
            return {"is_distress": False, "confidence": 0.0, "emotion": "unknown"}

        # RMS energy (loud ≈ distress)
        rms = float(np.sqrt(np.mean(y ** 2)))

        # Fundamental frequency variance (high variance ≈ emotional speech)
        f0, _, _ = librosa.pyin(y, fmin=50, fmax=500, sr=sr)
        f0_clean = f0[~np.isnan(f0)] if f0 is not None else np.array([])
        f0_std = float(np.std(f0_clean)) if len(f0_clean) > 10 else 0.0

        # Zero-crossing rate (high ≈ noisy/panic)
        zcr = float(librosa.feature.zero_crossing_rate(y).mean())

        score = 0.0
        score += min(rms / 0.15, 1.0) * 0.40      # energy weight
        score += min(f0_std / 80.0, 1.0) * 0.35   # pitch instability weight
        score += min(zcr / 0.20, 1.0) * 0.25      # noise weight

        is_distress = score >= settings.DISTRESS_DETECTION_THRESHOLD
        emotion = "distress" if is_distress else ("nervous" if score > 0.45 else "neutral")

        return {"is_distress": is_distress, "confidence": round(min(score, 1.0), 3), "emotion": emotion}

    except ImportError:
        # No librosa — minimal byte-level energy check
        arr = np.frombuffer(audio_bytes[:8000], dtype=np.int16).astype(np.float32)
        rms = float(np.sqrt(np.mean(arr ** 2))) / 32768
        is_distress = rms > 0.25
        return {"is_distress": is_distress, "confidence": round(min(rms * 2, 1.0), 3), "emotion": "unknown"}
    except Exception as exc:
        logger.error("Heuristic distress check failed: %s", exc)
        return {"is_distress": False, "confidence": 0.0, "emotion": "unknown"}


class DistressDetector:
    """
    Public interface consumed by voice_detection.py API route.
    """

    @staticmethod
    async def analyze(audio_bytes: bytes) -> dict:
        """
        Returns:
            {
                "is_distress": bool,
                "confidence": float (0.0–1.0),
                "emotion": str,
                "method": "model" | "heuristic"
            }
        """
        if not settings.ML_ENABLED:
            return {"is_distress": False, "confidence": 0.0, "emotion": "unknown", "method": "disabled"}

        model = _load_model()

        if model is not None:
            features = _extract_features(audio_bytes)
            if features is not None:
                try:
                    proba = model.predict_proba(features)[0]
                    classes = model.classes_
                    # Build emotion → probability map
                    proba_map = dict(zip(classes, proba))
                    distress_prob = sum(proba_map.get(e, 0.0) for e in DISTRESS_EMOTIONS)
                    top_emotion = max(proba_map, key=proba_map.get)
                    is_distress = distress_prob >= settings.DISTRESS_DETECTION_THRESHOLD
                    return {
                        "is_distress": is_distress,
                        "confidence": round(distress_prob, 3),
                        "emotion": top_emotion,
                        "method": "model",
                    }
                except Exception as exc:
                    logger.warning("Model inference failed (%s) — falling back to heuristics", exc)

        result = _heuristic_distress(audio_bytes)
        result["method"] = "heuristic"
        logger.debug("Distress heuristic result: %s", result)
        return result


    @staticmethod
    def train_model(
        audio_paths: list[str],
        labels: list[str],
        save_path: str = MODEL_PATH,
    ) -> None:
        """
        Train a Random Forest classifier on MFCC features.
        Intended to be run as a one-off training script.
        Usage:
            from app.ml.distress_detection import DistressDetector
            DistressDetector.train_model(paths, labels)
        """
        import joblib
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.preprocessing import LabelEncoder
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import classification_report

        X, y = [], []
        for path, label in zip(audio_paths, labels):
            with open(path, "rb") as f:
                feats = _extract_features(f.read())
            if feats is not None:
                X.append(feats[0])
                y.append(label)

        if not X:
            raise ValueError("No valid audio features extracted")

        X_arr = np.array(X)
        le = LabelEncoder()
        y_enc = le.fit_transform(y)

        X_train, X_test, y_train, y_test = train_test_split(X_arr, y_enc, test_size=0.2, random_state=42)
        clf = RandomForestClassifier(n_estimators=200, max_depth=20, n_jobs=-1, random_state=42)
        clf.fit(X_train, y_train)
        clf.classes_ = le.classes_

        preds = clf.predict(X_test)
        print(classification_report(y_test, preds, target_names=le.classes_))

        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        joblib.dump(clf, save_path)
        logger.info("Distress model saved to %s", save_path)
