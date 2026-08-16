"""
CLI Demo Runner for Warehouse Tire Counter
Usage:
  python demo_counter.py --source samples/conveyor_sample.mp4
  python demo_counter.py --source 0
  python demo_counter.py --source "rtsp://user:pass@192.168.1.50:554/stream"
"""

import argparse
import os
import sys
import cv2
from tire_counter import TireCounter

def main():
    parser = argparse.ArgumentParser(description="Warehouse Tire Counter CLI")
    parser.add_argument("--source", type=str, default="samples/conveyor_sample.mp4", help="Video file path, camera index (0, 1), or RTSP URL")
    parser.add_argument("--model", type=str, default="yolov8n.pt", help="YOLO model path or YOLO-World weight (e.g. yolov8s-worldv2.pt, yolov8n.pt, or custom_tire.pt)")
    parser.add_argument("--conf", type=float, default=0.25, help="Confidence threshold")
    parser.add_argument("--line-y", type=int, default=240, help="Y-coordinate for horizontal counting line")
    parser.add_argument("--output", type=str, default="output_counted.mp4", help="Path to save annotated output video (optional)")
    parser.add_argument("--no-display", action="store_true", help="Disable GUI window display")
    parser.add_argument("--export-json", type=str, default="counter_logs.json", help="Path to export count logs")
    args = parser.parse_args()

    # Determine input source
    source = int(args.source) if args.source.isdigit() else args.source

    # Check if sample video is needed and doesn't exist yet
    if isinstance(source, str) and not os.path.exists(source) and "sample" in source:
        print(f"[Demo] Source {source} not found. Generating synthetic test video...")
        from generate_sample_video import create_synthetic_tire_video
        create_synthetic_tire_video(source)

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"[Error] Could not open video source: {source}")
        sys.exit(1)

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0

    print("=" * 60)
    print("🚀 WAREHOUSE TIRE OBJECT COUNTER")
    print(f" Source      : {source} ({width}x{height} @ {fps:.1f} FPS)")
    print(f" Model       : {args.model}")
    print(f" Line Pos    : Y = {args.line_y}")
    print("=" * 60)

    # Initialize counter
    counter = TireCounter(
        model_path=args.model,
        conf_threshold=args.conf,
        line_points=[(50, args.line_y), (width - 50, args.line_y)],
    )

    # Video writer for output
    writer = None
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(args.output, fourcc, fps, (width, height))

    frame_count = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_count += 1
            annotated_frame, summary = counter.process_frame(frame, draw_annotated=True)

            if writer:
                writer.write(annotated_frame)

            if not args.no_display:
                cv2.imshow("Warehouse Tire Counter - Live Feed", annotated_frame)
                key = cv2.waitKey(1) & 0xFF
                if key == 27 or key == ord('q'):
                    print("\n[Demo] Stopped by user (q pressed).")
                    break

            if frame_count % 30 == 0:
                print(f"Frame {frame_count:04d} | IN: {summary['in_count']} | OUT: {summary['out_count']} | In-View: {summary['live_in_view']}")

    finally:
        cap.release()
        if writer:
            writer.release()
            print(f"[Demo] Annotated video saved to: {args.output}")
        cv2.destroyAllWindows()

        counter.export_logs(args.export_json)

        print("=" * 60)
        print("📊 FINAL COUNTING SUMMARY")
        print(f" Total IN (Incoming) : {counter.in_count}")
        print(f" Total OUT (Outgoing): {counter.out_count}")
        print(f" Net Stock Change    : +{counter.in_count - counter.out_count}")
        print("=" * 60)

if __name__ == "__main__":
    main()
