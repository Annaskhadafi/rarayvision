"""
Mining & OTR (Off-The-Road) Giant Tire Open Yard Stock Counter
Designed for heavy equipment open yards (Caterpillar, Komatsu, Liebherr dump truck tires).

Supports:
- Multi-Zone Yard Segmentation (e.g. New Tires Bay, Scrap Bay, Ready-for-Mount Bay)
- Stack Multiplier (counts stacks or calculates total units in multi-tier vertical stacks)
- Zero-Shot YOLO-World (Giant Tire, OTR Tire, Mining Wheel) or Custom Fine-Tuned Weights
"""

import argparse
import os
import sys
import cv2
import numpy as np
from tire_counter import TireCounter

def generate_mining_yard_sample_video(output_path: str = "samples/mining_yard_sample.mp4", num_frames: int = 150):
    """
    Generates a simulated open mining yard (dirt ground) with stationary tire stacks
    in distinct bays and moving tire handlers / transport.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    width, height = 800, 600
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, 20.0, (width, height))

    # Yard Bays / Zones
    # Bay A: New OTR Tires (Top Left)
    # Bay B: Used / Scrap OTR (Top Right)
    # Bay C: Inspection / Mount (Bottom Left)
    # Roadway: Bottom Right

    # Stationary giant tires: (x, y, radius, label)
    stationary_tires = [
        # Bay A (New)
        {"x": 120, "y": 140, "r": 42},
        {"x": 220, "y": 140, "r": 42},
        {"x": 120, "y": 240, "r": 42},
        {"x": 220, "y": 240, "r": 42},
        {"x": 300, "y": 180, "r": 45},

        # Bay B (Scrap)
        {"x": 520, "y": 150, "r": 40},
        {"x": 620, "y": 150, "r": 40},
        {"x": 710, "y": 160, "r": 38},
        {"x": 580, "y": 240, "r": 40},
        {"x": 670, "y": 250, "r": 42},

        # Bay C (Active / Mount)
        {"x": 150, "y": 450, "r": 44},
        {"x": 260, "y": 460, "r": 44},
    ]

    for frame_idx in range(num_frames):
        # Open yard dirt/gravel background (brownish earthy tone)
        frame = np.full((height, width, 3), (45, 65, 80), dtype=np.uint8)

        # Ground texture variations
        cv2.rectangle(frame, (20, 20), (370, 320), (50, 75, 95), -1)  # Bay A ground
        cv2.rectangle(frame, (430, 20), (780, 320), (40, 60, 75), -1)  # Bay B ground
        cv2.rectangle(frame, (20, 360), (370, 580), (55, 80, 100), -1) # Bay C ground
        
        # Haul road path
        cv2.rectangle(frame, (420, 360), (780, 580), (35, 50, 65), -1)

        # Draw stationary giant tires
        for t in stationary_tires:
            cx, cy, r = t["x"], t["y"], t["r"]
            # Outer massive tread (heavy deep lugs)
            cv2.circle(frame, (cx, cy), r, (20, 22, 25), -1)
            cv2.circle(frame, (cx, cy), r, (10, 10, 12), 4)
            # Sidewall
            cv2.circle(frame, (cx, cy), int(r * 0.75), (35, 38, 42), 3)
            # Massive inner bore
            cv2.circle(frame, (cx, cy), int(r * 0.5), (70, 95, 115), -1)
            cv2.circle(frame, (cx, cy), int(r * 0.5), (20, 25, 30), 2)

        # Draw 1 moving tire being transported across haul road (moving left to right)
        moving_x = int(430 + (frame_idx * 2.2))
        moving_y = 470
        if moving_x < 760:
            # Moving giant tire
            cv2.circle(frame, (moving_x, moving_y), 45, (20, 22, 25), -1)
            cv2.circle(frame, (moving_x, moving_y), 45, (10, 10, 12), 4)
            cv2.circle(frame, (moving_x, moving_y), int(45 * 0.5), (60, 80, 95), -1)

        out.write(frame)

    out.release()
    print(f"[Sample Generator] Created simulated mining yard video: {output_path}")

def main():
    parser = argparse.ArgumentParser(description="Mining OTR Giant Tire Open Yard Stock Counter")
    parser.add_argument("--source", type=str, default="samples/mining_yard_sample.mp4", help="Video file, CCTV RTSP URL, or webcam")
    parser.add_argument("--model", type=str, default="yolov8s-worldv2.pt", help="YOLO model or YOLO-World weight")
    parser.add_argument("--conf", type=float, default=0.20, help="Confidence threshold for giant tires")
    parser.add_argument("--no-display", action="store_true", help="Disable GUI display")
    parser.add_argument("--output", type=str, default="output_mining_yard.mp4", help="Output annotated video path")
    args = parser.parse_args()

    # Source handling
    source = int(args.source) if args.source.isdigit() else args.source
    if isinstance(source, str) and not os.path.exists(source) and "sample" in source:
        generate_mining_yard_sample_video(source)

    # Define Yard Zones (Polygons for outdoor bays)
    # Default layout for 800x600 resolution (adjust coordinates to match your CCTV view)
    yard_zones = {
        "Bay-A (New OTR)": [(20, 20), (370, 20), (370, 320), (20, 320)],
        "Bay-B (Scrap / Used)": [(430, 20), (780, 20), (780, 320), (430, 320)],
        "Bay-C (Mounting Bay)": [(20, 360), (370, 360), (370, 580), (20, 580)],
        "Transit Road": [(420, 360), (780, 360), (780, 580), (420, 580)],
    }

    # Line for counting tires entering/leaving transit road
    transit_line = [(420, 470), (780, 470)]

    print("=" * 65)
    print("🚜 MINING OTR GIANT TIRE - OPEN YARD STOCK COUNTER")
    print(f" Source        : {source}")
    print(f" Model         : {args.model}")
    print(f" Configured Bays: {list(yard_zones.keys())}")
    print("=" * 65)

    counter = TireCounter(
        model_path=args.model,
        conf_threshold=args.conf,
        zones=yard_zones,
        line_points=transit_line,
        classes_to_detect=["giant tire", "mining tire", "OTR tire", "heavy equipment tire", "large tire", "tire"],
    )

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"[Error] Failed to open video stream: {source}")
        sys.exit(1)

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 800
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 600
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0

    writer = None
    if args.output:
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(args.output, fourcc, fps, (width, height))

    frame_idx = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_idx += 1
            annotated_frame, summary = counter.process_frame(frame, draw_annotated=True)

            if writer:
                writer.write(annotated_frame)

            if not args.no_display:
                cv2.imshow("Mining Yard OTR Tire Stock Monitoring", annotated_frame)
                key = cv2.waitKey(1) & 0xFF
                if key == 27 or key == ord('q'):
                    print("\n[Stopped] User exited.")
                    break

            if frame_idx % 30 == 0:
                print(f"Frame {frame_idx:04d} | Total In-Yard: {summary['total_live_count']} | Zones: {summary['zone_counts']}")

    finally:
        cap.release()
        if writer:
            writer.release()
            print(f"[Saved] Annotated video saved to: {args.output}")
        cv2.destroyAllWindows()

        counter.export_logs("mining_yard_stock_logs.json")

        print("=" * 65)
        print("📊 MINING YARD INVENTORY SUMMARY")
        print(f" Total Live OTR Tires Detected : {counter.total_live_count}")
        print(" Breakdown per Bay:")
        for bay, count in counter.current_zone_counts.items():
            print(f"   • {bay:<25}: {count} units")
        print("=" * 65)

if __name__ == "__main__":
    main()
