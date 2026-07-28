"""
Emotion Detection ML module.
Classifies speech into 8 core emotions using MFCC + spectral features.
Emotions: neutral, calm, happy, sad, angry, fearful, disgust, surprised

Primary  — Multi-class Random Forest / SVM on RAVDESS features
Fallback — Energy + pitch variance → simplified 3-class (calm / agitated / distress)

Model: app/ml/models/emotion_model.pkl
"""
import io
import logging
import os
from typing import Optional

import numpy as np

from app.config import settings

logger = logging.getLogger("safeher.ml.emotion")

EMOTION_LABELS = ["neutral", "calm", "happy", "sad", "angry", "fearful", "disgust", "surprised"]
DANGER_EMOTIONS = {"angry", "fearful", "disgust"}   # flag for safety concern
MODEL_PATH = os.path.join(settings.ML_MODELS_DIR, "emotion_model.pkl")

_model = None


def _load_model():
    global _model
    if _model is not None:
        return _model
    try:
        import joblib
        if os.path.exists(MODEL_PATH):
            _model = joblib.load(MODEL_PATH)
            logger.info("Emotion model loaded from %s", MODEL_PATH)
        else:
            logger.warning("Emotion model not found — using simplified heuristic")
    except Exception as exc:
        logger.warning("Emotion model failed to load: %s", exc)
    return _model


def _extract_emotion_features(audio_bytes: bytes) -> Optional[np.ndarray]:
    try:
        import librosa

        y, sr = librosa.load(io.BytesIO(audio_bytes), sr=22050, mono=True, duration=30.0)
        if len(y) < sr * 0.3:
            return None

        # MFCC (40 coefficients) + deltas
        mfcc        = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=40)
        mfcc_d1     = librosa.feature.delta(mfcc)
        mfcc_d2     = librosa.feature.delta(mfcc, order=2)

        # Spectral features
        chroma      = librosa.feature.chroma_stft(y=y, sr=sr)
        contrast    = librosa.feature.spectral_contrast(y=y, sr=sr)
        centroid    = librosa.feature.spectral_centroid(y=y, sr=sr)
        bandwidth   = librosa.feature.spectral_bandwidth(y=y, sr=sr)
        rolloff     = librosa.feature.spectral_rolloff(y=y, sr=sr)
        zcr         = librosa.feature.zero_crossing_rate(y)

        # Prosodic (pitch)
        f0, _, _    = librosa.pyin(y, fmin=50, fmax=600, sr=sr)
        f0c         = f0[~np.isnan(f0)] if f0 is not None else np.zeros(1)
        f0_stats    = np.array([f0c.mean(), f0c.std(), f0c.min(), f0c.max()])

        # Energy
        rms         = librosa.feature.rms(y=y)

        def stats(arr):
            return np.array([arr.mean(), arr.std(), arr.min(), arr.max()])

        features = np.concatenate([
            stats(mfcc),    stats(mfcc_d1),  stats(mfcc_d2),
            stats(chroma),  stats(contrast), stats(centroid),
            stats(bandwidth), stats(rolloff), stats(zcr), stats(rms),
            f0_stats,
        ])
        return features.reshape(1, -1)

    except ImportError:
        return None
    except Exception as exc:
        logger.error("Emotion feature extraction failed: %s", exc)
        return None


def _heuristic_emotion(audio_bytes: bytes) -> dict:
    """
    Simplified 3-state emotion: calm | agitated | distress.
    Based on energy + pitch variance only.
    """
    try:
        import librosa
        y, sr = librosa.load(io.BytesIO(audio_bytes), sr=22050, mono=True, duration=30.0)
        if len(y) == 0:
            return {"emotion": "neutral", "confidence": 0.5, "is_danger_emotion": False}

        rms = float(np.sqrt(np.mean(y ** 2)))

        f0, _, _ = librosa.pyin(y, fmin=50, fmax=600, sr=sr)
        f0c = f0[~np.isnan(f0)] if f0 is not None else np.zeros(1)
        f0_std = float(np.std(f0c)) if len(f0c) > 5 else 0.0

        if rms > 0.15 and f0_std > 60:
            emotion, confidence = "fearful", min(rms * 5, 1.0)
        elif rms > 0.10:
            emotion, confidence = "angry", min(rms * 4, 1.0)
        elif f0_std > 40:
            emotion, confidence = "sad", 0.55
        else:
            emotion, confidence = "neutral", 0.70

        return {
            "emotion": emotion,
            "confidence": round(confidence, 3),
            "is_danger_emotion": emotion in DANGER_EMOTIONS,
        }
    except ImportError:
        return {"emotion": "neutral", "confidence": 0.5, "is_danger_emotion": False}
    except Exception as exc:
        logger.error("Heuristic emotion failed: %s", exc)
        return {"emotion": "unknown", "confidence": 0.0, "is_danger_emotion": False}


class EmotionDetector:

    @staticmethod
    async def analyze(audio_bytes: bytes) -> dict:
        """
        Returns:
            {
                "emotion": str,
                "confidence": float,
                "is_danger_emotion": bool,
                "all_scores": dict[str, float],
                "method": str
            }
        """
        if not settings.ML_ENABLED:
            return {
                "emotion": "unknown", "confidence": 0.0,
                "is_danger_emotion": False, "all_scores": {},
                "method": "disabled",
            }

        model = _load_model()

        if model is not None:
            features = _extract_emotion_features(audio_bytes)
            if features is not None:
                try:
                    proba = model.predict_proba(features)[0]
                    classes = list(model.classes_)
                    proba_map = {c: round(float(p), 3) for c, p in zip(classes, proba)}
                    top_emotion = max(proba_map, key=proba_map.get)
                    confidence = proba_map[top_emotion]
                    return {
                        "emotion": top_emotion,
                        "confidence": confidence,
                        "is_danger_emotion": top_emotion in DANGER_EMOTIONS,
                        "all_scores": proba_map,
                        "method": "model",
                    }
                except Exception as exc:
                    logger.warning("Emotion model inference failed (%s) — heuristic", exc)

        result = _heuristic_emotion(audio_bytes)
        result["all_scores"] = {}
        result["method"] = "heuristic"
        return result


    @staticmethod
    def train_model(
        audio_paths: list[str],
        labels: list[str],
        save_path: str = MODEL_PATH,
    ) -> None:
        """
        Train a multi-class SVM emotion classifier.
        Labels should be one of EMOTION_LABELS.
        """
        import joblib
        from sklearn.svm import SVC
        from sklearn.preprocessing import StandardScaler, LabelEncoder
        from sklearn.pipeline import Pipeline
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import classification_report

        X, y = [], []
        for path, label in zip(audio_paths, labels):
            with open(path, "rb") as f:
                feats = _extract_emotion_features(f.read())
            if feats is not None:
                X.append(feats[0])
                y.append(label)

        if not X:
            raise ValueError("No audio features extracted")

        le = LabelEncoder()
        y_enc = le.fit_transform(y)
        X_arr = np.array(X)

        X_train, X_test, y_train, y_test = train_test_split(X_arr, y_enc, test_size=0.2, random_state=42)

        pipe = Pipeline([
            ("scaler", StandardScaler()),
            ("clf", SVC(kernel="rbf", probability=True, C=10, gamma="scale", class_weight="balanced")),
        ])
        pipe.fit(X_train, y_train)
        pipe.classes_ = le.classes_

        preds = pipe.predict(X_test)
        print(classification_report(y_test, preds, target_names=le.classes_))

        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        joblib.dump(pipe, save_path)
        logger.info("Emotion model saved to %s", save_path)
