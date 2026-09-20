import os
import requests
import json
from typing import List, Dict, Any, Optional
from datetime import datetime

try:
    from app.core.config import LABEL_STUDIO_URL, LABEL_STUDIO_API_KEY, LABEL_STUDIO_PROJECT_ID
except ImportError:
    from backend.app.core.config import LABEL_STUDIO_URL, LABEL_STUDIO_API_KEY, LABEL_STUDIO_PROJECT_ID

class LabelStudioService:
    def __init__(self):
        self.base_url = LABEL_STUDIO_URL.rstrip("/")
        self.api_key = LABEL_STUDIO_API_KEY
        self.default_project_id = LABEL_STUDIO_PROJECT_ID

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json"
        }
        if self.api_key:
            headers["Authorization"] = f"Token {self.api_key}"
        return headers

    def test_connection(self) -> Dict[str, Any]:
        """Check connection to Label Studio instance."""
        try:
            url = f"{self.base_url}/api/projects"
            resp = requests.get(url, headers=self._headers(), timeout=5)
            if resp.status_code in (200, 201):
                return {"connected": True, "projects_count": len(resp.json())}
            return {"connected": False, "status_code": resp.status_code, "error": resp.text}
        except Exception as e:
            return {"connected": False, "error": str(e)}

    def format_detection_to_ls_annotation(
        self,
        detections: List[Dict[str, Any]],
        img_width: int = 1000,
        img_height: int = 1000,
        from_name: str = "label",
        to_name: str = "image"
    ) -> List[Dict[str, Any]]:
        """
        Convert detection results to Label Studio pre-annotation results format.
        Detection item schema:
        {
          "box": [x1, y1, x2, y2], # in pixels or absolute
          "label": "car",
          "confidence": 0.95
        }
        """
        results = []
        for i, det in enumerate(detections):
            # Feedback annotations use x/y/width/height; model detections use
            # the legacy [x1, y1, x2, y2] box. Accept both contracts.
            if "box" in det:
                box = det.get("box", [0, 0, 0, 0])
            else:
                box = [
                    det.get("x", 0),
                    det.get("y", 0),
                    det.get("x", 0) + det.get("width", 0),
                    det.get("y", 0) + det.get("height", 0),
                ]
            label = det.get("label", "object")
            score = det.get("confidence", 1.0)

            x1, y1, x2, y2 = box[0], box[1], box[2], box[3]
            w = max(0.0, x2 - x1)
            h = max(0.0, y2 - y1)

            # Convert to percentage 0-100%
            x_pct = (x1 / img_width) * 100.0 if img_width > 0 else 0.0
            y_pct = (y1 / img_height) * 100.0 if img_height > 0 else 0.0
            w_pct = (w / img_width) * 100.0 if img_width > 0 else 0.0
            h_pct = (h / img_height) * 100.0 if img_height > 0 else 0.0

            results.append({
                "id": f"result_{i}",
                "type": "rectanglelabels",
                "from_name": from_name,
                "to_name": to_name,
                "original_width": img_width,
                "original_height": img_height,
                "image_rotation": 0,
                "value": {
                    "rotation": 0,
                    "x": max(0.0, min(100.0, x_pct)),
                    "y": max(0.0, min(100.0, y_pct)),
                    "width": max(0.0, min(100.0, w_pct)),
                    "height": max(0.0, min(100.0, h_pct)),
                    "rectanglelabels": [label]
                },
                "score": score
            })
        return results

    def push_task(
        self,
        image_url: str,
        detections: Optional[List[Dict[str, Any]]] = None,
        img_width: int = 1000,
        img_height: int = 1000,
        meta_info: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Push a single image task (optionally with pre-annotations) to Label Studio."""
        pid = project_id or self.default_project_id
        url = f"{self.base_url}/api/projects/{pid}/tasks"

        data_payload = {
            "image": image_url
        }
        if meta_info:
            data_payload.update(meta_info)

        task_payload: Dict[str, Any] = {
            "data": data_payload
        }

        # If we have detections, create pre-annotations
        if detections and len(detections) > 0:
            ls_results = self.format_detection_to_ls_annotation(detections, img_width, img_height)
            task_payload["predictions"] = [
                {
                    "model_version": meta_info.get("model_version", "current") if meta_info else "current",
                    "result": ls_results
                }
            ]

        try:
            resp = requests.post(url, json=task_payload, headers=self._headers(), timeout=10)
            if resp.status_code in (200, 201):
                return {"success": True, "task": resp.json()}
            return {"success": False, "status_code": resp.status_code, "error": resp.text}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def push_bulk_tasks(self, tasks: List[Dict[str, Any]], project_id: Optional[str] = None) -> Dict[str, Any]:
        """Bulk import tasks to Label Studio."""
        pid = project_id or self.default_project_id
        url = f"{self.base_url}/api/projects/{pid}/tasks/bulk"

        try:
            resp = requests.post(url, json=tasks, headers=self._headers(), timeout=30)
            if resp.status_code in (200, 201):
                return {"success": True, "imported_count": len(tasks), "response": resp.json()}
            return {"success": False, "status_code": resp.status_code, "error": resp.text}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def convert_coco_to_label_studio(
        self,
        coco_json: Dict[str, Any],
        image_url_mapping: Dict[str, str]
    ) -> List[Dict[str, Any]]:
        """
        Convert COCO JSON dictionary into Label Studio tasks format.
        coco_json keys: images, annotations, categories.
        image_url_mapping: {file_name: accessible_s3_url}
        """
        categories = {cat["id"]: cat["name"] for cat in coco_json.get("categories", [])}
        images_dict = {img["id"]: img for img in coco_json.get("images", [])}

        annotations_by_image: Dict[int, List[Dict[str, Any]]] = {}
        for ann in coco_json.get("annotations", []):
            img_id = ann["image_id"]
            if img_id not in annotations_by_image:
                annotations_by_image[img_id] = []
            annotations_by_image[img_id].append(ann)

        tasks = []
        for img_id, img_info in images_dict.items():
            file_name = img_info.get("file_name", "")
            image_url = image_url_mapping.get(file_name, file_name)
            img_w = img_info.get("width", 1000)
            img_h = img_info.get("height", 1000)

            anns = annotations_by_image.get(img_id, [])
            results = []
            for i, ann in enumerate(anns):
                cat_name = categories.get(ann.get("category_id"), "object")
                # COCO bbox: [x, y, width, height]
                bbox = ann.get("bbox", [0, 0, 0, 0])
                bx, by, bw, bh = bbox[0], bbox[1], bbox[2], bbox[3]

                x_pct = (bx / img_w) * 100.0 if img_w > 0 else 0.0
                y_pct = (by / img_h) * 100.0 if img_h > 0 else 0.0
                w_pct = (bw / img_w) * 100.0 if img_w > 0 else 0.0
                h_pct = (bh / img_h) * 100.0 if img_h > 0 else 0.0

                results.append({
                    "id": f"coco_ann_{i}",
                    "type": "rectanglelabels",
                    "from_name": "label",
                    "to_name": "image",
                    "original_width": img_w,
                    "original_height": img_h,
                    "image_rotation": 0,
                    "value": {
                        "rotation": 0,
                        "x": max(0.0, min(100.0, x_pct)),
                        "y": max(0.0, min(100.0, y_pct)),
                        "width": max(0.0, min(100.0, w_pct)),
                        "height": max(0.0, min(100.0, h_pct)),
                        "rectanglelabels": [cat_name]
                    }
                })

            task_obj = {
                "data": {
                    "image": image_url,
                    "original_filename": file_name
                }
            }
            if results:
                task_obj["annotations"] = [
                    {
                        "result": results
                    }
                ]
            tasks.append(task_obj)

        return tasks


# Singleton instance
label_studio_service = LabelStudioService()
