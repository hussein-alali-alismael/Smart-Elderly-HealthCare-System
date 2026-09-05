"""YOLOv8-pose ONNX inference and pose-based fall scoring for Raspberry Pi."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import cv2
import numpy as np
import onnxruntime as ort

POSE_SIZE = 320
KEYPOINT_COUNT = 17
PERSON_CONFIDENCE = 0.35
NMS_IOU_THRESHOLD = 0.45
KEYPOINT_CONFIDENCE = 0.25

# COCO keypoint indexes used by YOLOv8 pose models.
NOSE = 0
LEFT_SHOULDER, RIGHT_SHOULDER = 5, 6
LEFT_HIP, RIGHT_HIP = 11, 12


@dataclass
class PoseDetection:
    confidence: float
    box: tuple[int, int, int, int]
    keypoints: np.ndarray
    pose_score: float


class YOLOPoseFallModel:
    """Run a YOLOv8-pose ONNX model and score posture/motion as a fall."""

    def __init__(self, model_path: str, threshold: float = 0.55, providers: list[str] | None = None):
        self.session = ort.InferenceSession(
            model_path,
            providers=providers or ["CPUExecutionProvider"],
        )
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        self.threshold = threshold

    @staticmethod
    def _sigmoid(value: np.ndarray | float) -> np.ndarray | float:
        return 1.0 / (1.0 + np.exp(-value))

    def _preprocess(self, frame: np.ndarray) -> tuple[np.ndarray, float, float]:
        height, width = frame.shape[:2]
        resized = cv2.resize(frame, (POSE_SIZE, POSE_SIZE), interpolation=cv2.INTER_LINEAR)
        image = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        return np.transpose(image, (2, 0, 1))[np.newaxis], width / POSE_SIZE, height / POSE_SIZE

    def _decode(self, raw: np.ndarray, scale_x: float, scale_y: float, width: int, height: int) -> list[PoseDetection]:
        predictions = np.squeeze(raw)
        if predictions.ndim != 2:
            raise ValueError(f"Unexpected YOLO pose output shape: {raw.shape}")
        # Ultralytics ONNX pose output is [1, 56, N]; transpose to [N, 56].
        if predictions.shape[0] <= 60 and predictions.shape[1] > predictions.shape[0]:
            predictions = predictions.T
        detections = []
        for prediction in predictions:
            if prediction.shape[0] < 5 + KEYPOINT_COUNT * 3:
                continue
            confidence = float(prediction[4])
            if confidence < PERSON_CONFIDENCE:
                continue
            cx, cy, box_width, box_height = map(float, prediction[:4])
            x1 = max(0, int((cx - box_width / 2) * scale_x))
            y1 = max(0, int((cy - box_height / 2) * scale_y))
            x2 = min(width - 1, int((cx + box_width / 2) * scale_x))
            y2 = min(height - 1, int((cy + box_height / 2) * scale_y))
            keypoints = prediction[5:5 + KEYPOINT_COUNT * 3].reshape(KEYPOINT_COUNT, 3).copy()
            keypoints[:, 0] *= scale_x
            keypoints[:, 1] *= scale_y
            # Some exports provide keypoint confidence as logits.
            if np.any((keypoints[:, 2] < 0) | (keypoints[:, 2] > 1)):
                keypoints[:, 2] = self._sigmoid(keypoints[:, 2])
            detections.append(PoseDetection(confidence, (x1, y1, x2, y2), keypoints, float(np.mean(keypoints[:, 2]))))
        return self._nms(detections)

    @staticmethod
    def _nms(detections: list[PoseDetection]) -> list[PoseDetection]:
        """Collapse overlapping YOLO candidates into one box per person.

        ONNX exports return many candidate rows for the same person. Without
        NMS, the dashboard counts those rows as separate people.
        """
        ordered = sorted(detections, key=lambda item: item.confidence, reverse=True)
        kept: list[PoseDetection] = []
        for candidate in ordered:
            x1, y1, x2, y2 = candidate.box
            candidate_area = max(0, x2 - x1) * max(0, y2 - y1)
            overlaps = False
            for existing in kept:
                ex1, ey1, ex2, ey2 = existing.box
                intersection_width = max(0, min(x2, ex2) - max(x1, ex1))
                intersection_height = max(0, min(y2, ey2) - max(y1, ey1))
                intersection = intersection_width * intersection_height
                existing_area = max(0, ex2 - ex1) * max(0, ey2 - ey1)
                union = candidate_area + existing_area - intersection
                if union and intersection / union >= NMS_IOU_THRESHOLD:
                    overlaps = True
                    break
            if not overlaps:
                kept.append(candidate)
        return kept

    def predict(self, frame: np.ndarray, previous_center_y: float | None, previous_time: float | None, now: float) -> dict[str, Any]:
        height, width = frame.shape[:2]
        input_image, scale_x, scale_y = self._preprocess(frame)
        raw = cast(np.ndarray, self.session.run([self.output_name], {self.input_name: input_image})[0])
        detections = self._decode(raw, scale_x, scale_y, width, height)
        if not detections:
            return {"confidence": 0.0, "fall": False, "status": "NO PERSON", "detections": [], "center_y": None}

        detection = detections[0]
        points = detection.keypoints
        shoulder_points = points[[LEFT_SHOULDER, RIGHT_SHOULDER]]
        hip_points = points[[LEFT_HIP, RIGHT_HIP]]
        visible_shoulders = shoulder_points[shoulder_points[:, 2] >= KEYPOINT_CONFIDENCE]
        visible_hips = hip_points[hip_points[:, 2] >= KEYPOINT_CONFIDENCE]
        if len(visible_shoulders) == 0 or len(visible_hips) == 0:
            return {"confidence": 0.0, "fall": False, "status": "PERSON", "detections": detections, "center_y": None}

        shoulder_y = float(np.mean(visible_shoulders[:, 1]))
        hip_y = float(np.mean(visible_hips[:, 1]))
        torso_height = max(abs(hip_y - shoulder_y), 1.0)
        x1, y1, x2, y2 = detection.box
        aspect_ratio = (x2 - x1) / max(y2 - y1, 1)
        center_y = (shoulder_y + hip_y) / 2.0
        velocity = 0.0
        if previous_center_y is not None and previous_time is not None and now > previous_time:
            velocity = (center_y - previous_center_y) / (now - previous_time)

        # Use more than the bounding-box ratio. A person can fall sideways,
        # toward the camera, or be partly occluded, so the torso orientation
        # and motion provide useful evidence when the box is not horizontal.
        shoulder_x = float(np.mean(visible_shoulders[:, 0]))
        hip_x = float(np.mean(visible_hips[:, 0]))
        torso_width = max(abs(hip_x - shoulder_x), 1.0)
        torso_diagonal = max(float(np.hypot(torso_width, torso_height)), 1.0)
        torso_horizontal = min(max(torso_width / torso_diagonal, 0.0), 1.0)
        horizontal_pose = min(max((aspect_ratio - 0.65) / 1.35, 0.0), 1.0)
        orientation_pose = min(max((torso_horizontal - 0.35) / 0.55, 0.0), 1.0)
        posture_score = max(horizontal_pose, orientation_pose)
        rapid_downward_motion = min(max(velocity / 300.0, 0.0), 1.0)
        low_torso = min(max((aspect_ratio - 1.0) / 1.4, 0.0), 1.0)
        pose_quality = min(max(detection.pose_score, 0.0), 1.0)
        # Keep a usable score when one or two landmarks are weak. The model's
        # pose quality is still a factor, but it no longer suppresses every
        # partially occluded fall to zero.
        quality_factor = 0.65 + 0.35 * pose_quality
        fall_confidence = min(1.0, (posture_score * 0.60 + rapid_downward_motion * 0.25 + low_torso * 0.15) * quality_factor)
        is_fall = fall_confidence >= self.threshold
        status = "FALL" if is_fall else ("LYING" if posture_score >= 0.55 else "STANDING")
        return {
            "confidence": float(fall_confidence), "fall": is_fall, "status": status,
            "detections": detections, "center_y": center_y, "velocity": velocity,
            "aspect_ratio": aspect_ratio, "torso_height": torso_height,
            "posture_score": posture_score, "motion_score": rapid_downward_motion,
            "pose_quality": pose_quality,
        }


def draw_pose_result(frame: np.ndarray, result: dict[str, Any]) -> np.ndarray:
    """Draw blue person boxes, keypoints, skeleton, and pose fall status."""
    for detection in result.get("detections", []):
        x1, y1, x2, y2 = detection.box
        color = (0, 0, 255) if result.get("fall") else (255, 0, 0)  # BGR: red/blue
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, f"Person {detection.confidence:.2f}", (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        for x, y, confidence in detection.keypoints:
            if confidence >= KEYPOINT_CONFIDENCE:
                cv2.circle(frame, (int(x), int(y)), 3, (255, 0, 0), -1)
    status = result.get("status", "MONITOR")
    confidence = float(result.get("confidence", 0.0))
    banner_color = (0, 0, 180) if result.get("fall") else (30, 100, 30)
    cv2.rectangle(frame, (0, 0), (350, 72), banner_color, -1)
    label = f"FALL DETECTED  {confidence:.2f}" if result.get("fall") else f"{status}  CONFIDENCE {confidence:.2f}"
    cv2.putText(frame, label, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
    cv2.putText(frame, f"People: {len(result.get('detections', []))}", (10, 57), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1)
    return frame


__all__ = ["YOLOPoseFallModel", "draw_pose_result", "PoseDetection"]
