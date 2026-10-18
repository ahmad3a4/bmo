"""
BMO Face ID — local face recognition via OpenCV Haar cascade detection +
LBPH recognition.

Deliberately not face_recognition/dlib: that needs a from-source compile on
Pi's aarch64 with no prebuilt wheel. opencv-contrib-python-headless ships a
prebuilt aarch64 wheel and LBPH is more than good enough for recognizing a
handful of known people.

Mirrors bmo/voiceprint.py's API shape (enroll/identify/forget/list_known) —
same kind of biometric recognition, just a different sense.
"""
import os
import glob
import shutil

import cv2
import numpy as np

from bmo.paths import KNOWN_FACES_DIR, FACE_CASCADE_PATH
from bmo.camera import has_camera, capture

CAPTURE_PATH = "/tmp/bmo_face_capture.jpg"
GLANCE_PATH  = "/tmp/bmo_glance.jpg"
ENROLL_SHOTS = 5


class FaceIDManager:
    def __init__(self, enabled=True, threshold=70.0):
        self.enabled = enabled
        self.threshold = threshold  # LBPH distance — LOWER means a better match
        self._cascade = None
        self._recognizer = None
        self._labels = {}  # {int_label: name}
        if not self.enabled:
            return
        if not os.path.exists(FACE_CASCADE_PATH):
            print(f"[FACEID] Haar cascade not found at {FACE_CASCADE_PATH} — face ID disabled.", flush=True)
            self.enabled = False
            return
        self._cascade = cv2.CascadeClassifier(FACE_CASCADE_PATH)
        os.makedirs(KNOWN_FACES_DIR, exist_ok=True)
        self._train()
        print(f"[FACEID] Ready. {len(self._labels)} known face(s): "
              f"{', '.join(self._labels.values()) or '(none)'}", flush=True)

    def _detect_largest_face(self, img_path):
        img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        faces = self._cascade.detectMultiScale(img, scaleFactor=1.2, minNeighbors=5, minSize=(80, 80))
        if len(faces) == 0:
            return None
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        return cv2.resize(img[y:y + h, x:x + w], (200, 200))

    def _train(self):
        names = sorted(d for d in os.listdir(KNOWN_FACES_DIR)
                        if os.path.isdir(os.path.join(KNOWN_FACES_DIR, d)))
        self._labels = dict(enumerate(names))
        name_to_id = {n: i for i, n in self._labels.items()}

        faces, labels = [], []
        for name in names:
            for path in glob.glob(os.path.join(KNOWN_FACES_DIR, name, "*.png")):
                img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
                if img is not None:
                    faces.append(img)
                    labels.append(name_to_id[name])

        self._recognizer = cv2.face.LBPHFaceRecognizer_create()
        if faces:
            self._recognizer.train(faces, np.array(labels))

    def enroll(self, name):
        if not self.enabled:
            return "Face ID isn't set up right now."
        if not has_camera():
            return "I don't have a camera hooked up right now."

        person_dir = os.path.join(KNOWN_FACES_DIR, name)
        os.makedirs(person_dir, exist_ok=True)
        existing = len(glob.glob(os.path.join(person_dir, "*.png")))

        saved = 0
        for _ in range(ENROLL_SHOTS):
            path = capture(CAPTURE_PATH, width=640, height=480, label="FACEID")
            if not path:
                continue
            face = self._detect_largest_face(path)
            if face is None:
                continue
            cv2.imwrite(os.path.join(person_dir, f"{existing + saved}.png"), face)
            saved += 1

        if saved == 0:
            return f"I couldn't get a clear look at your face, {name}. Try again with better lighting?"

        self._train()
        return f"Got it! I'll remember what {name} looks like now. ({saved} photo{'s' if saved != 1 else ''} saved.)"

    def identify(self):
        """Returns the best-matching known name, or None if unknown/disabled/no camera."""
        if not self.enabled or not self._labels or not has_camera():
            return None

        path = capture(CAPTURE_PATH, width=640, height=480, label="FACEID")
        if not path:
            return None
        face = self._detect_largest_face(path)
        if face is None:
            return None
        return self._match(face)

    def look(self):
        """Silent glance: None if the camera is unusable, else {"face": bool, "name": str | None}."""
        if not self.enabled or not has_camera():
            return None
        path = capture(GLANCE_PATH, width=640, height=480, label="FACEID")
        if not path:
            return None
        face = self._detect_largest_face(path)
        if face is None:
            return {"face": False, "name": None}
        return {"face": True, "name": self._match(face)}

    def _match(self, face):
        if not self._labels:
            return None
        label_id, distance = self._recognizer.predict(face)
        best_name = self._labels.get(label_id)
        matched = best_name if distance <= self.threshold else None
        print(f"[FACEID] Best match: {best_name} (distance {distance:.1f}, "
              f"threshold {self.threshold}) → {'MATCH' if matched else 'no match'}", flush=True)
        return matched

    def forget(self, name):
        person_dir = os.path.join(KNOWN_FACES_DIR, name)
        if not os.path.isdir(person_dir):
            return f"I don't know anyone named {name} by face."
        shutil.rmtree(person_dir)
        self._train()
        return f"Okay, I've forgotten what {name} looks like."

    def list_known(self):
        names = sorted(self._labels.values())
        if not names:
            return "I don't recognize anyone by face yet."
        return "I recognize these faces: " + ", ".join(names)
