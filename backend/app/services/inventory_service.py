import io
import time
import base64
import numpy as np
import cv2
from PIL import Image

try:
    import supervision as sv
except ImportError:
    sv = None

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None

# Model cache dictionary
_model_cache = {}

def get_yolo_model(model_name: str = "yolov8n"):
    """Fetch or load a cached YOLO model instance."""
    if YOLO is None:
        return None
    if model_name not in _model_cache:
        try:
            # Loads standard pre-trained YOLO model (downloads automatically if not cached)
            _model_cache[model_name] = YOLO(f"{model_name}.pt")
        except Exception as e:
            print(f"[InventoryService] Error loading model {model_name}: {e}")
            # Fallback to yolov8n
            if "yolov8n" not in _model_cache:
                _model_cache["yolov8n"] = YOLO("yolov8n.pt")
            return _model_cache["yolov8n"]
    return _model_cache.get(model_name)

def _image_bytes_to_cv2(image_bytes: bytes) -> np.ndarray:
    """Convert raw image or video bytes to OpenCV BGR numpy array."""
    try:
        pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    except Exception:
        # If PIL fails, attempt reading as video file via tempfile
        import tempfile
        import os
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
                tmp.write(image_bytes)
                tmp_path = tmp.name

            cap = cv2.VideoCapture(tmp_path)
            frame = None
            if cap.isOpened():
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 1)
                target_frame = max(0, total_frames // 2)
                cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
                ret, frame = cap.read()
                if not ret or frame is None:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ret, frame = cap.read()
            cap.release()

            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

            if frame is not None:
                return frame
        except Exception as err:
            print(f"[InventoryService] Video decoding error: {err}")
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

        raise ValueError("File gambar atau video tidak valid / corrupt")

def _cv2_to_base64(cv2_img: np.ndarray) -> str:
    """Convert OpenCV BGR image to base64 data URI string."""
    _, buffer = cv2.imencode(".jpg", cv2_img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    b64_str = base64.b64encode(buffer).decode("utf-8")
    return f"data:image/jpeg;base64,{b64_str}"

def process_count_boxes(
    image_bytes: bytes,
    confidence: float = 0.4,
    iou_threshold: float = 0.45,
    target_classes: list = None,
    model_name: str = "yolov8n"
) -> dict:
    """
    Counts boxes/pallets/items in an image using YOLO & Supervision annotators.
    """
    start_time = time.time()
    img_bgr = _image_bytes_to_cv2(image_bytes)
    h, w, _ = img_bgr.shape

    model = get_yolo_model(model_name)
    
    detections_list = []
    class_counts = {}
    total_count = 0
    annotated_b64 = _cv2_to_base64(img_bgr)

    if model is not None:
        results = model.predict(img_bgr, conf=confidence, iou=iou_threshold, verbose=False)[0]
        
        if sv is not None:
            sv_detections = sv.Detections.from_ultralytics(results)
            
            # Filter target classes if provided
            if target_classes and len(target_classes) > 0:
                target_classes_lower = [c.lower() for c in target_classes]
                valid_indices = []
                for i, class_id in enumerate(sv_detections.class_id):
                    name = model.names.get(class_id, "object").lower()
                    if name in target_classes_lower or "box" in name or "container" in name or "suitcase" in name:
                        valid_indices.append(i)
                if len(valid_indices) > 0:
                    sv_detections = sv_detections[np.array(valid_indices)]

            total_count = len(sv_detections)

            # Build detection list & class breakdown
            for bbox, conf, class_id in zip(sv_detections.xyxy, sv_detections.confidence, sv_detections.class_id):
                cls_name = model.names.get(int(class_id), f"class_{class_id}")
                class_counts[cls_name] = class_counts.get(cls_name, 0) + 1
                detections_list.append({
                    "class": cls_name,
                    "confidence": round(float(conf), 3),
                    "bbox": [round(float(v), 1) for v in bbox]
                })

            # Supervision Annotations
            box_annotator = sv.BoxAnnotator(thickness=2)
            label_annotator = sv.LabelAnnotator(text_scale=0.5, text_padding=4)
            labels = [f"{model.names.get(int(cid), 'obj')} {conf:.2f}" for cid, conf in zip(sv_detections.class_id, sv_detections.confidence)]
            
            annotated_frame = box_annotator.annotate(scene=img_bgr.copy(), detections=sv_detections)
            annotated_frame = label_annotator.annotate(scene=annotated_frame, detections=sv_detections, labels=labels)
            
            # Add summary header banner on image
            cv2.rectangle(annotated_frame, (0, 0), (w, 40), (20, 20, 20), -1)
            cv2.putText(annotated_frame, f"INVENTORY AUDIT | Total Count: {total_count} items", (15, 26),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 200), 2)
            
            annotated_b64 = _cv2_to_base64(annotated_frame)
        else:
            # Fallback when supervision is not installed
            for box in results.boxes:
                cls_id = int(box.cls[0])
                cls_name = model.names.get(cls_id, f"class_{cls_id}")
                conf = float(box.conf[0])
                bbox = [float(v) for v in box.xyxy[0]]
                class_counts[cls_name] = class_counts.get(cls_name, 0) + 1
                detections_list.append({
                    "class": cls_name,
                    "confidence": round(conf, 3),
                    "bbox": [round(v, 1) for v in bbox]
                })
            total_count = len(detections_list)

    proc_time = int((time.time() - start_time) * 1000)

    return {
        "total_count": total_count,
        "by_class": class_counts,
        "detections": detections_list,
        "annotated_image": annotated_b64,
        "processing_ms": proc_time,
        "model_used": model_name,
        "confidence_used": confidence
    }

def process_defect_check(
    image_bytes: bytes,
    confidence: float = 0.35,
    model_name: str = "yolov8n"
) -> dict:
    """
    Inspects packages/boxes for physical damage or structural deformation.
    """
    start_time = time.time()
    img_bgr = _image_bytes_to_cv2(image_bytes)
    h, w, _ = img_bgr.shape

    model = get_yolo_model(model_name)
    annotated_frame = img_bgr.copy()
    
    defects = []
    overall_status = "INTACT"

    # Analyze box edges and contours for irregularities (dent / deformation heuristic)
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    
    # Calculate edge density & contour variance as damage indicator
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    irregular_contours = 0

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area > 1500:
            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.04 * peri, True)
            # Boxes are usually 4-corner polygons; non-standard shapes signify crushes/dents
            if len(approx) > 6:
                irregular_contours += 1
                x, y, bw, bh = cv2.boundingRect(cnt)
                defects.append({
                    "type": "SURFACE_DEFORMATION",
                    "severity": "MEDIUM" if area < 5000 else "HIGH",
                    "bbox": [int(x), int(y), int(x + bw), int(y + bh)],
                    "confidence": round(min(0.95, 0.5 + (area / 20000.0)), 2)
                })
                cv2.rectangle(annotated_frame, (x, y), (x + bw, y + bh), (0, 0, 255), 2)
                cv2.putText(annotated_frame, f"DEFECT ({defects[-1]['severity']})", (x, max(20, y - 5)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)

    if irregular_contours > 0:
        overall_status = "DEFECT_DETECTED"

    # Banner header
    status_color = (0, 255, 0) if overall_status == "INTACT" else (0, 0, 255)
    cv2.rectangle(annotated_frame, (0, 0), (w, 40), (20, 20, 20), -1)
    cv2.putText(annotated_frame, f"PACKAGING QUALITY: {overall_status} | Defects found: {len(defects)}", (15, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, status_color, 2)

    proc_time = int((time.time() - start_time) * 1000)

    return {
        "status": overall_status,
        "defects_count": len(defects),
        "defects": defects,
        "annotated_image": _cv2_to_base64(annotated_frame),
        "processing_ms": proc_time,
        "model_used": model_name
    }

def process_shelf_occupancy(
    image_bytes: bytes,
    grid_rows: int = 3,
    grid_cols: int = 4,
    confidence: float = 0.4,
    model_name: str = "yolov8n"
) -> dict:
    """
    Calculates shelf space occupancy percentage by dividing shelf view into a grid.
    """
    start_time = time.time()
    img_bgr = _image_bytes_to_cv2(image_bytes)
    h, w, _ = img_bgr.shape

    model = get_yolo_model(model_name)
    
    # Grid cell dimensions
    cell_h = h // grid_rows
    cell_w = w // grid_cols
    
    grid_cells = []
    occupied_cells = 0
    total_cells = grid_rows * grid_cols

    # Detect items using YOLO
    item_bboxes = []
    if model is not None:
        results = model.predict(img_bgr, conf=confidence, verbose=False)[0]
        for box in results.boxes:
            bbox = [float(v) for v in box.xyxy[0]]
            item_bboxes.append(bbox)

    annotated_frame = img_bgr.copy()

    # Evaluate each grid cell
    for r in range(grid_rows):
        for c in range(grid_cols):
            x1 = c * cell_w
            y1 = r * cell_h
            x2 = (c + 1) * cell_w if c < grid_cols - 1 else w
            y2 = (r + 1) * cell_h if r < grid_rows - 1 else h
            
            # Check if any item falls into this cell
            is_occupied = False
            cell_items = 0
            for box in item_bboxes:
                cx = (box[0] + box[2]) / 2.0
                cy = (box[1] + box[3]) / 2.0
                if x1 <= cx <= x2 and y1 <= cy <= y2:
                    is_occupied = True
                    cell_items += 1
            
            if is_occupied:
                occupied_cells += 1

            # Annotate grid cell
            cell_color = (0, 200, 0) if is_occupied else (0, 0, 230)
            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), cell_color, 2)
            cell_label = f"R{r+1}C{c+1}: {'OCCUPIED (' + str(cell_items) + ')' if is_occupied else 'EMPTY'}"
            cv2.putText(annotated_frame, cell_label, (x1 + 8, y1 + 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, cell_color, 1)

    occupancy_pct = round((occupied_cells / total_cells) * 100.0, 1)

    # Banner header
    cv2.rectangle(annotated_frame, (0, 0), (w, 40), (20, 20, 20), -1)
    cv2.putText(annotated_frame, f"SHELF OCCUPANCY: {occupancy_pct}% ({occupied_cells}/{total_cells} cells occupied)", (15, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)

    proc_time = int((time.time() - start_time) * 1000)

    return {
        "occupancy_percentage": occupancy_pct,
        "occupied_cells": occupied_cells,
        "total_cells": total_cells,
        "empty_cells": total_cells - occupied_cells,
        "grid": f"{grid_rows}x{grid_cols}",
        "annotated_image": _cv2_to_base64(annotated_frame),
        "processing_ms": proc_time,
        "model_used": model_name
    }
