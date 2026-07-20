from direction_counter import DirectionCounter

FRAME_H = 720  # line_y = 720 * 0.5 = 360


def run_frame(dc, boxes, frame_index):
    """boxes: list (x, y) tam box. Tra ve list ket qua update() theo dung
    thu tu, roi tu goi end_frame() 1 lan - giong dung cach main.py dung."""
    results = [dc.update(x, y, FRAME_H, frame_index) for x, y in boxes]
    dc.end_frame(frame_index)
    return results


def main():
    dc = DirectionCounter(y_ratio=0.5, band_px=20, cell_px=60, miss_tolerance_frames=10)

    print("--- Xe A dung/di cham qua vach o x=100, nam trong dai (line_y=360) suot 4 khung ---")
    print("Ky vong: CHI khung dau tien tra True, 3 khung sau None (van cung 1 o, chua roi dai)")
    for i in range(4):
        r = run_frame(dc, [(100, 360)], i + 1)
        print(f"frame {i+1}: {r}")

    print("\n--- Xe A roi khoi dai HAN (y=200, ngoai band) trong 15 khung lien tuc (> miss_tolerance=10) ---")
    print("Ky vong: o duoc giai phong that su sau khi vuot qua nguong khoan dung")
    for i in range(15):
        run_frame(dc, [(100, 200)], 4 + 1 + i)

    print("--- Xe MOI cung xuat hien lai o x=100 trong dai - phai duoc dem lai (True) ---")
    r = run_frame(dc, [(100, 360)], 4 + 1 + 15 + 1)
    print(f"frame {4 + 1 + 15 + 1}: {r}  (ky vong [True])")

    print("\n--- Xe DUNG YEN o x=100 nhung detection CHOP TAT (grace period phai hap thu duoc) ---")
    dc_flicker = DirectionCounter(y_ratio=0.5, band_px=20, cell_px=60, miss_tolerance_frames=5)
    detected_pattern = [True, True, False, True, True, True, False, False, True, True]
    total = 0
    for i, seen in enumerate(detected_pattern):
        boxes = [(100, 360)] if seen else []
        r = run_frame(dc_flicker, boxes, i + 1)
        if r and r[0] is True:
            total += 1
        print(f"frame {i+1}: detect={seen} -> {r}")
    print(f"TONG DEM: {total}  (ky vong 1 - xe dung yen, chi bi chop tat detection, KHONG duoc dem nhieu lan)")

    print("\n--- 1 xe DUY NHAT di CHEO (truot tu o 9 sang o 10, cell_px=40) trong luc con trong dai ---")
    print("Ky vong: CHI dem 1 lan du truot qua ranh gioi o (khong phai 2 xe khac nhau)")
    dc_diag = DirectionCounter(y_ratio=0.5, band_px=20, cell_px=40, miss_tolerance_frames=10)
    x, y = 380.0, 340.0
    total_diag = 0
    frame = 0
    while y < 400:
        frame += 1
        r = run_frame(dc_diag, [(x, y)], frame)
        if r and r[0] is True:
            total_diag += 1
        x += 4.0
        y += 4.0
    print(f"TONG DEM: {total_diag}  (ky vong 1)")

    print("\n--- 2 xe cat vach CUNG LUC o 2 vi tri X khac nhau (x=100 va x=400, cach nhau > cell_px) ---")
    dc2 = DirectionCounter(y_ratio=0.5, band_px=20, cell_px=60)
    r = run_frame(dc2, [(100, 360), (400, 355)], 1)
    print(f"frame 1: {r}  (ky vong ca 2 deu True - khong dua vao track_id nen khong bi tranh nhau)")

    print("\n--- Box nam ngoai dai quanh vach (y=200, cach line_y=360 hon band_px=20) - KHONG duoc dem ---")
    dc3 = DirectionCounter(y_ratio=0.5, band_px=20, cell_px=60)
    r = run_frame(dc3, [(100, 200)], 1)
    print(f"frame 1: {r}  (ky vong [None])")


if __name__ == "__main__":
    main()
