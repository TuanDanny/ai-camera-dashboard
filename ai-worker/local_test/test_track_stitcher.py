"""
Kiem chung TrackStitcher: gia lap 4 kich ban voi track_id gia (khong dung
YOLO/ByteTrack that) de xac nhan logic ghep ID hoat dung dung nhu thiet ke
truoc khi dua vao main.py that.
"""
import sys

AI_WORKER_DIR = "/home/shtp/ai-camera-dashboard/ai-worker"
sys.path.insert(0, AI_WORKER_DIR)

from track_stitcher import TrackStitcher  # noqa: E402


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    return condition


def test_reappear_within_window_same_canonical():
    print("\n--- Kich ban 1: mat dau roi xuat hien lai GAN do, trong cua so cho phep ---")
    st = TrackStitcher(max_distance_px=50, min_gap_frames=30, max_gap_frames=60)

    # raw_id=1 xuat hien tu frame 1 den frame 10, dung yen tai (100, 100)
    for f in range(1, 11):
        cid = st.resolve(raw_id=1, x=100, y=100, frame_index=f)
    assert cid == 1

    # ByteTrack mat dau tu frame 11, roi cap raw_id=2 MOI tai frame 50
    # (gap = 50 - 10 = 40, nam giua 30 va 60 - dung vung "khoang giua")
    # vi tri gan (105, 102) - gan voi vi tri cuoi cua raw_id=1
    cid2 = st.resolve(raw_id=2, x=105, y=102, frame_index=50)

    return check("raw_id=2 phai duoc ghep ve canonical_id=1 (cung 1 xe)", cid2 == 1)


def test_reappear_too_far_new_id():
    print("\n--- Kich ban 2: xuat hien lai nhung QUA XA vi tri cu -> phai la xe khac ---")
    st = TrackStitcher(max_distance_px=50, min_gap_frames=30, max_gap_frames=60)

    for f in range(1, 11):
        cid = st.resolve(raw_id=1, x=100, y=100, frame_index=f)

    # raw_id=2 xuat hien tai frame 50 (gap hop le = 40) nhung cach xa 300px
    cid2 = st.resolve(raw_id=2, x=400, y=100, frame_index=50)

    return check("raw_id=2 qua xa -> phai la canonical_id moi (=2), khong ghep",
                 cid2 == 2)


def test_reappear_too_late_new_id():
    print("\n--- Kich ban 3: xuat hien lai nhung QUA LAU (ngoai cua so) -> phai la xe khac ---")
    st = TrackStitcher(max_distance_px=50, min_gap_frames=30, max_gap_frames=60)

    for f in range(1, 11):
        cid = st.resolve(raw_id=1, x=100, y=100, frame_index=f)

    # raw_id=2 xuat hien tai frame 100 (gap = 100 - 10 = 90, vuot max_gap_frames=60)
    cid2 = st.resolve(raw_id=2, x=102, y=101, frame_index=100)

    return check("raw_id=2 qua lau (gap=90 > 60) -> phai la canonical_id moi (=2)",
                 cid2 == 2)


def test_active_track_never_stolen():
    print("\n--- Kich ban 4: 1 track dang ACTIVE khong duoc bi 'cuop' boi track moi gan do ---")
    st = TrackStitcher(max_distance_px=50, min_gap_frames=30, max_gap_frames=60)

    # raw_id=1 dang active lien tuc tu frame 1 den frame 50 (khong he mat dau)
    for f in range(1, 51):
        cid1 = st.resolve(raw_id=1, x=100, y=100, frame_index=f)

    # Ngay tai frame 51, mot raw_id=2 HOAN TOAN moi xuat hien ngay ke ben
    # (chi cach nhau vai px) - day la 1 xe THAT SU khac (vi du: 2 xe chay
    # song song), khong phai xe 1 "song lai" vi xe 1 van dang active.
    cid2 = st.resolve(raw_id=2, x=103, y=101, frame_index=51)

    return check("raw_id=2 phai la canonical_id moi (=2), KHONG ghep vao id=1 dang active",
                 cid2 == 2)


def main():
    results = [
        test_reappear_within_window_same_canonical(),
        test_reappear_too_far_new_id(),
        test_reappear_too_late_new_id(),
        test_active_track_never_stolen(),
    ]

    print(f"\n=== Ket qua: {sum(results)}/{len(results)} kich ban PASS ===")
    if all(results):
        print("TAT CA PASS")
    else:
        print("CO KICH BAN FAIL - kiem tra lai truoc khi dua vao main.py")


if __name__ == "__main__":
    main()
