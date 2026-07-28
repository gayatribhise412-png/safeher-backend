"""
Scream Detection ML module.
Architecture:
  • Primary  — binary CNN/SVM classifier trained on urban sounds + scream dataset
  • Fallback — spectral peak + energy burst heuristics

Model file: app/ml/models/scream_model.pkl

Training data recommendations:
  - UrbanSound8K dataset (screaming class)
  - ESC-50 (human sounds)
  - Custom recorded scream/non-scream clips
"""
import io
import logging
import os
from typing import Optional

import numpy as np

from app.config import settings

logger = logging.getLogger("safeher.ml.scream")

MODEL_PATH = os.path.join(settings.ML_MODELS_DIR, "scream_model.pkl")
_model = None


def _load_model():
    global _model
    if _model is not None:
        return _model
    try:
        import joblib
        if os.path.exists(MODEL_PATH):
            _model = joblib.load(MODEL_PATH)
            logger.info("Scream model loaded from %s", MODEL_PATH)
        else:
            logger.warning("Scream model not found at %s — using heuristics", MODEL_PATH)
    except Exception as exc:
        logger.warning("Scream model load failed (%s)", exc)
    return _model


def _extract_scream_features(audio_bytes: bytes) -> Optional[np.ndarray]:
    """
    Features optimised for scream detection:
    - Mel-spectrogram statistics (screams have distinct mel patterns)
    - MFCC delta coefficients (sudden change ≈ scream onset)
    - Spectral rolloff (screams are high-frequency dominant)
    - Onset strength (abrupt energy burst)
    """
    try:
        import librosa
        y, sr = librosa.load(io.BytesIO(audio_bytes), sr=22050, mono=True, duration=30.0)

        if len(y) < sr * 0.3:
            return None

        # Mel spectrogram
        mel = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=64)
        mel_db = librosa.power_to_db(mel, ref=np.max)
        mel_stats = np.concatenate([mel_db.mean(axis=1), mel_db.std(axis=1)])  # 128

        # MFCC + deltas
        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=20)
        mfcc_delta = librosa.feature.delta(mfcc)
        mfcc_stats = np.concatenate([
            mfcc.mean(axis=1), mfcc.std(axis=1),         # 40
            mfcc_delta.mean(axis=1), mfcc_delta.std(axis=1),  # 40
        ])

        # Spectral rolloff (high freq dominance)
        rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr)
        rolloff_mean = float(rolloff.mean())

        # RMS energy + peak
        rms = librosa.feature.rms(y=y)
        rms_mean = float(rms.mean())
        rms_max = float(rms.max())

        # Onset strength (sudden bursts)
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        onset_max = float(onset_env.max())
        onset_mean = float(onset_env.mean())

        features = np.concatenate([
            mel_stats, mfcc_stats,
            [rolloff_mean, rms_mean, rms_max, onset_max, onset_mean],
        ])
        return features.reshape(1, -1)

    except ImportError:
        return None
    except Exception as exc:
        logger.error("Scream feature extraction failed: %s", exc)
        return None


def _heuristic_scream(audio_bytes: bytes) -> dict:
    """
    Frequency + energy burst heuristic for scream detection.
    Screams are characterised by:
      - High energy (RMS > 0.12)
      - High-frequency dominance (spectral centroid > 3000 Hz)
      - Sharp onset (onset_strength peak > 8)
    """
    try:
        import librosa
        y, sr = librosa.load(io.BytesIO(audio_bytes), sr=22050, mono=True, duration=30.0)
        if len(y) == 0:
            return {"is_scream": False, "confidence": 0.0}

        rms = float(np.sqrt(np.mean(y ** 2)))
        centroid = float(librosa.feature.spectral_centroid(y=y, sr=sr).mean())
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        onset_peak = float(onset_env.max())

        # Weighted scoring
        energy_score = min(rms / 0.15, 1.0) * 0.40
        freq_score   = min(centroid / 4000.0, 1.0) * 0.35
        onset_score  = min(onset_peak / 10.0, 1.0) * 0.25
        total = energy_score + freq_score + onset_score

        is_scream = total >= settings.SCREAM_DETECTION_THRESHOLD
        return {"is_scream": is_scream, "confidence": round(min(total, 1.0), 3)}

    except ImportError:
        arr = np.frombuffer(audio_bytes[:8000], dtype=np.int16).astype(np.float32)
        rms = float(np.sqrt(np.mean(arr ** 2))) / 32768
        is_scream = rms > 0.30
        return {"is_scream": is_scream, "confidence": round(min(rms * 2.5, 1.0), 3)}
    except Exception as exc:
        logger.error("Heuristic scream detection failed: %s", exc)
        return {"is_scream": False, "confidence": 0.0}


class ScreamDetector:

    @staticmethod
    async def analyze(audio_bytes: bytes) -> dict:
        """
        Returns:
            {
                "is_scream": bool,
                "confidence": float,
                "method": "model" | "heuristic" | "disabled"
            }
        """
        if not settings.ML_ENABLED:
            return {"is_scream": False, "confidence": 0.0, "method": "disabled"}

        model = _load_model()

        if model is not None:
            features = _extract_scream_features(audio_bytes)
            if features is not None:
                try:
                    proba = model.predict_proba(features)[0]
                    # Assumes binary: [no_scream, scream] or model.classes_ = [0, 1]
                    scream_idx = list(model.classes_).index(1) if 1 in model.classes_ else 1
                    confidence = float(proba[scream_idx])
                    is_scream = confidence >= settings.SCREAM_DETECTION_THRESHOLD
                    return {"is_scream": is_scream, "confidence": round(confidence, 3), "method": "model"}
                except Exception as exc:
                    logger.warning("Scream model inference failed (%s) — heuristics", exc)

        result = _heuristic_scream(audio_bytes)
        result["method"] = "heuristic"
        return result


    @staticmethod
    def train_model(
        audio_paths: list[str],
        labels: list[int],   # 1 = scream, 0 = non-scream
        save_path: str = MODEL_PATH,
    ) -> None:
        """
        Train a binary SVM scream classifier.
        Usage:
            ScreamDetector.train_model(paths, labels)
        """
        import joblib
        from sklearn.svm import SVC
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline import Pipeline
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import classification_report

        X, y = [], []
        for path, label in zip(audio_paths, labels):
            with open(path, "rb") as f:
                feats = _extract_scream_features(f.read())
            if feats is not None:
                X.append(feats[0])
                y.append(label)

        if not X:
            raise ValueError("No features extracted — check audio files")

        X_arr = np.array(X)
        X_train, X_test, y_train, y_test = train_test_split(X_arr, y, test_size=0.2, random_state=42)

        pipe = Pipeline([
            ("scaler", StandardScaler()),
            ("clf", SVC(kernel="rbf", probability=True, C=10, gamma="scale")),
        ])
        pipe.fit(X_train, y_train)
        pipe.classes_ = np.array([0, 1])

        preds = pipe.predict(X_test)
        print(classification_report(y_test, preds, target_names=["non-scream", "scream"]))

        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        joblib.dump(pipe, save_path)
        logger.info("Scream model saved to %s", save_path)
