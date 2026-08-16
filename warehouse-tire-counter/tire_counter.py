"""
Warehouse Tire Object Counter Engine
Built on top of Ultralytics YOLO & ByteTrack
"""

import os
import cv2
import json
import time
import numpy as np
from datetime import datetime
from typing import List, Tuple, Dict, Any, Optional
from ultralytics import YOLO

class TireCounter:
    """
    Object Counter designed for Warehouse Inventory and Conveyor Stock Monitoring.
    Supports:
      - Line Crossing (In / Out counting)
      - Polygon Area / Region Stock Counting
      - Zero-shot YOLO-World or Custom Trained YOLO weights
      - Real-time logging & export
    """

    def __init__(
        self,
        model_path: str = "yolov8s-worldv2.pt",
        classes_to_detect: Optional[List[str]] = None,
        conf_threshold: float = 0.25,
        iou_threshold: float = 0.5,
        line_points: Optional[List[Tuple[int, int]]] = None,
        zones: Optional[Dict[str, List[Tuple[int, int]]]] = None,
        device: str = "cpu",
    ):
        self.model_path = model_path
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.device = device

        # Load YOLO model
        print(f"[TireCounter] Loading model from: {model_path} on {device}...")
        self.model = YOLO(model_path)

        # Specialized classes for Mining / OTR Giant Tires
        if "world" in model_path.lower():
            target_classes = classes_to_detect or [
                "giant tire",
                "mining tire",
                "OTR tire",
                "heavy equipment tire",
                "large tire",
                "tire stack",
                "tire",
                "wheel"
            ]
            print(f"[TireCounter] Setting YOLO-World mining/OTR classes: {target_classes}")
            self.model.set_classes(target_classes)
            self.target_classes = target_classes
        else:
            self.target_classes = classes_to_detect

        # Counting Geometry
        self.line_points = line_points
        # Multi-Zone Dictionary: {"Zone_A": [(x1,y1), (x2,y2), ...], "Zone_B": [...]}
        self.zones = zones or {}

        # Tracking & Stock state
        self.in_count = 0
        self.out_count = 0
        self.current_zone_counts: Dict[str, int] = {k: 0 for k in self.zones}
        self.total_live_count = 0
        self.counted_ids = set()
        self.track_history: Dict[int, List[Tuple[int, int]]] = {}
        self.event_logs: List[Dict[str, Any]] = []

    def _point_in_polygon(self, point: Tuple[int, int], polygon: List[Tuple[int, int]]) -> bool:
        """Ray-casting algorithm to determine if a point is inside a polygon."""
        x, y = point
        n = len(polygon)
        inside = False
        p1x, p1y = polygon[0]
        for i in range(n + 1):
            p2x, p2y = polygon[i % n]
            if y > min(p1y, p2y):
                if y <= max(p1y, p2y):
                    if x <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                        if p1x == p2x or x <= xinters:
                            inside = not inside
            p1x, p1y = p2x, p2y
        return inside

    def _is_crossing_line(self, prev_pt: Tuple[int, int], curr_pt: Tuple[int, int], p1: Tuple[int, int], p2: Tuple[int, int]) -> Optional[str]:
        """
        Determines if movement from prev_pt to curr_pt crossed line (p1 -> p2)
        and indicates direction ('IN' or 'OUT').
        """
        def ccw(A, B, C):
            return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0])

        A, B = p1, p2
        C, D = prev_pt, curr_pt

        intersect = (ccw(A, C, D) != ccw(B, C, D)) and (ccw(A, B, C) != ccw(A, B, D))
        if intersect:
            # Determine direction based on y-delta or relative vector
            if curr_pt[1] > prev_pt[1]:
                return "IN"  # Moving downward
            else:
                return "OUT"  # Moving upward
        return None

    def process_frame(self, frame: cv2.Mat, draw_annotated: bool = True) -> Tuple[cv2.Mat, Dict[str, Any]]:
        """
        Processes a single frame: performs tracking, updates counts, and draws overlays.
        """
        annotated_frame = frame.copy() if draw_annotated else frame
        h, w = frame.shape[:2]

        # Run tracking using ByteTrack
        results = self.model.track(
            frame,
            persist=True,
            conf=self.conf_threshold,
            iou=self.iou_threshold,
            device=self.device,
            verbose=False,
        )

        detected_in_zone = 0
        zone_counts = {k: 0 for k in self.zones}
        current_frame_tracks = []

        if results and results[0].boxes is not None and results[0].boxes.id is not None:
            boxes = results[0].boxes.xyxy.cpu().numpy()
            track_ids = results[0].boxes.id.int().cpu().numpy().tolist()
            confs = results[0].boxes.conf.cpu().numpy().tolist()
            clss = results[0].boxes.cls.int().cpu().numpy().tolist()
            names = results[0].names

            for box, track_id, conf, cls_id in zip(boxes, track_ids, confs, clss):
                x1, y1, x2, y2 = map(int, box)
                cx = (x1 + x2) // 2
                cy = (y1 + y2) // 2
                class_name = names.get(cls_id, f"cls_{cls_id}")

                current_frame_tracks.append({
                    "track_id": track_id,
                    "class": class_name,
                    "conf": float(conf),
                    "bbox": [x1, y1, x2, y2],
                    "center": [cx, cy]
                })

                # Record tracking history
                if track_id not in self.track_history:
                    self.track_history[track_id] = []
                self.track_history[track_id].append((cx, cy))
                if len(self.track_history[track_id]) > 30:
                    self.track_history[track_id].pop(0)

                # Zone / Polygon membership check
                for zone_name, poly in self.zones.items():
                    if len(poly) >= 3 and self._point_in_polygon((cx, cy), poly):
                        zone_counts[zone_name] += 1

                # Line crossing logic
                if self.line_points and len(self.line_points) == 2 and len(self.track_history[track_id]) >= 2:
                    prev_pt = self.track_history[track_id][-2]
                    curr_pt = (cx, cy)
                    direction = self._is_crossing_line(prev_pt, curr_pt, self.line_points[0], self.line_points[1])

                    if direction and track_id not in self.counted_ids:
                        self.counted_ids.add(track_id)
                        if direction == "IN":
                            self.in_count += 1
                        else:
                            self.out_count += 1

                        # Log event
                        event = {
                            "timestamp": datetime.now().isoformat(),
                            "track_id": int(track_id),
                            "class": class_name,
                            "direction": direction,
                            "in_total": self.in_count,
                            "out_total": self.out_count,
                        }
                        self.event_logs.append(event)
                        print(f"[TireCounter EVENT] ID #{track_id} crossed line ({direction}) -> IN: {self.in_count} | OUT: {self.out_count}")

                # Draw bounding box & track trail
                if draw_annotated:
                    cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 220, 100), 2)
                    label = f"#{track_id} {class_name} {conf:.2f}"
                    cv2.putText(annotated_frame, label, (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 120), 1)
                    cv2.circle(annotated_frame, (cx, cy), 4, (0, 0, 255), -1)

                    # Draw movement trail
                    pts = self.track_history[track_id]
                    for i in range(1, len(pts)):
                        cv2.line(annotated_frame, pts[i - 1], pts[i], (255, 180, 0), 2)

                detected_in_zone += 1

        self.total_live_count = detected_in_zone
        self.current_zone_counts = zone_counts

        # Draw overlays: Zones, Line, Counts HUD
        if draw_annotated:
            # Draw multi-zones polygons
            for idx, (zone_name, poly) in enumerate(self.zones.items()):
                if len(poly) >= 3:
                    pts_np = np.array(poly, np.int32).reshape((-1, 1, 2))
                    # Semi-transparent zone overlay
                    overlay = annotated_frame.copy()
                    color = [(0, 165, 255), (255, 100, 0), (0, 255, 200), (200, 50, 255)][idx % 4]
                    cv2.fillPoly(overlay, [pts_np], color)
                    cv2.addWeighted(overlay, 0.15, annotated_frame, 0.85, 0, annotated_frame)
                    cv2.polylines(annotated_frame, [pts_np], True, color, 2)

                    # Zone label with live count
                    zx, zy = poly[0]
                    cv2.putText(annotated_frame, f"{zone_name}: {zone_counts.get(zone_name, 0)} tires", (zx, max(25, zy - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

            # Draw line if enabled
            if self.line_points and len(self.line_points) == 2:
                p1, p2 = self.line_points
                cv2.line(annotated_frame, p1, p2, (0, 140, 255), 3)
                cv2.putText(annotated_frame, "COUNTING LINE", (p1[0] + 10, p1[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 140, 255), 2)

            # Draw HUD card
            hud_h = 105 + (len(self.zones) * 22)
            cv2.rectangle(annotated_frame, (15, 15), (320, hud_h), (20, 20, 20), -1)
            cv2.rectangle(annotated_frame, (15, 15), (320, hud_h), (80, 80, 80), 1)

            cv2.putText(annotated_frame, "MINING TIRE YARD STOCK", (25, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
            cv2.putText(annotated_frame, f"Total Live In-Yard : {self.total_live_count}", (25, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 120), 2)
            
            y_offset = 88
            if self.line_points:
                cv2.putText(annotated_frame, f"Line IN: {self.in_count} | OUT: {self.out_count}", (25, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (50, 180, 255), 1)
                y_offset += 22

            for z_name, z_count in zone_counts.items():
                cv2.putText(annotated_frame, f" {z_name}: {z_count} units", (25, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
                y_offset += 22

        summary = {
            "total_live_count": self.total_live_count,
            "zone_counts": self.current_zone_counts,
            "in_count": self.in_count,
            "out_count": self.out_count,
            "active_tracks": len(current_frame_tracks),
            "tracks": current_frame_tracks,
        }

        return annotated_frame, summary

    def export_logs(self, output_path: str = "counter_logs.json"):
        """Exports event history and stock state to JSON."""
        with open(output_path, "w") as f:
            json.dump({
                "summary": {
                    "total_live_yard_count": self.total_live_count,
                    "zone_breakdown": self.current_zone_counts,
                    "total_in": self.in_count,
                    "total_out": self.out_count,
                    "final_stock_delta": self.in_count - self.out_count,
                },
                "events": self.event_logs
            }, f, indent=2)
        print(f"[TireCounter] Saved logs to {output_path}")
