import cv2
import numpy as np
import os

def create_synthetic_tire_video(output_path: str = "samples/conveyor_sample.mp4", num_frames: int = 150, width: int = 640, height: int = 480):
    """
    Creates a synthetic video simulating tires moving along a conveyor belt.
    Useful for testing the Object Counter pipeline.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, 25.0, (width, height))

    # Simulate 3 tires moving from top to bottom
    tires = [
        {"x": 220, "y": 30, "speed": 4, "radius": 45},
        {"x": 420, "y": -90, "speed": 3.8, "radius": 48},
        {"x": 320, "y": -230, "speed": 4.2, "radius": 42},
    ]

    for frame_idx in range(num_frames):
        # Background: Warehouse floor and conveyor
        frame = np.full((height, width, 3), (40, 45, 50), dtype=np.uint8)
        
        # Conveyor belt (vertical stripe)
        cv2.rectangle(frame, (120, 0), (520, height), (70, 75, 80), -1)
        cv2.rectangle(frame, (120, 0), (520, height), (120, 120, 120), 2)
        
        # Conveyor rollers/lines
        for y_line in range((frame_idx * 4) % 40, height, 40):
            cv2.line(frame, (125, y_line), (515, y_line), (60, 65, 70), 1)

        # Draw tires
        for t in tires:
            curr_y = int(t["y"] + frame_idx * t["speed"])
            curr_x = t["x"]
            r = t["radius"]
            if -r < curr_y < height + r:
                # Outer tire (black rubber)
                cv2.circle(frame, (curr_x, curr_y), r, (15, 15, 15), -1)
                cv2.circle(frame, (curr_x, curr_y), r, (35, 35, 35), 4)
                # Tread pattern
                cv2.circle(frame, (curr_x, curr_y), r - 6, (25, 25, 25), 2)
                # Rim / Inner circle (metallic)
                cv2.circle(frame, (curr_x, curr_y), int(r * 0.55), (160, 165, 170), -1)
                cv2.circle(frame, (curr_x, curr_y), int(r * 0.55), (100, 105, 110), 3)
                # Center cap
                cv2.circle(frame, (curr_x, curr_y), int(r * 0.2), (40, 40, 45), -1)

        out.write(frame)

    out.release()
    print(f"Generated synthetic test video: {output_path} ({num_frames} frames)")

if __name__ == "__main__":
    create_synthetic_tire_video("d:/[01] PROJECT/Raray VIsion/warehouse-tire-counter/samples/conveyor_sample.mp4")
