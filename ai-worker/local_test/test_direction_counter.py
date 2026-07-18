import sys

AI_WORKER_DIR = "/home/shtp/ai-camera-dashboard/ai-worker"
sys.path.insert(0, AI_WORKER_DIR)

from direction_counter import DirectionCounter  # noqa: E402

FRAME_H = 720  # line_y = 720 * 0.5 = 360


def main():
    dc = DirectionCounter(y_ratio=0.5, inbound_when="increasing")

    print("--- Track 1: di tu tren xuong duoi (300 -> 420), phai la INBOUND ---")
    for i, y in enumerate([300, 330, 350, 380, 420]):
        result = dc.update(track_id=1, centroid_y=y, frame_height=FRAME_H, frame_index=i + 1)
        print(f"frame {i+1}: y={y:>3} -> {result}")

    print("\n--- Track 2: chi di trong nua tren (100 -> 200), KHONG duoc cat qua ---")
    for i, y in enumerate([100, 150, 180, 200]):
        result = dc.update(track_id=2, centroid_y=y, frame_height=FRAME_H, frame_index=i + 1)
        print(f"frame {i+1}: y={y:>3} -> {result}")

    print("\n--- Track 1 (da dem roi o tren) dao dong qua lai gan duong, KHONG duoc dem them lan nao ---")
    for i, y in enumerate([420, 350, 400, 340, 410]):
        result = dc.update(track_id=1, centroid_y=y, frame_height=FRAME_H, frame_index=10 + i)
        print(f"frame {10+i}: y={y:>3} -> {result}  (ky vong luon None)")

    print("\n--- Track 3: di tu duoi len tren (420 -> 300), phai la OUTBOUND (nguoc voi inbound_when=increasing) ---")
    for i, y in enumerate([420, 390, 360, 330, 300]):
        result = dc.update(track_id=3, centroid_y=y, frame_height=FRAME_H, frame_index=i + 1)
        print(f"frame {i+1}: y={y:>3} -> {result}")

    print("\ncounted set:", dc.counted)


if __name__ == "__main__":
    main()
