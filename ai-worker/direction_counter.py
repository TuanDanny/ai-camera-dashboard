class DirectionCounter:
    """Phat hien "cat qua vach" tu detection YOLO THO - KHONG dung tracking/
    track_id (da bo ByteTrack hoan toan, xem npu_plan.md). Vi khong con biet
    "box nay o khung truoc chinh la box nao o khung sau", khong the so sanh
    vi tri truoc/sau cua CUNG 1 vat the nhu truoc nua -> khong con xac dinh
    duoc huong di chuyen thuc (inbound/outbound), chi con dem duoc TONG so
    lan cat vach.

    Thay track_id, dung "cell" (o chia theo truc X) lam danh tinh tam thoi:
    1 vat the dang nam trong dai mong quanh vach do se lam 1 o "ban" (chiem
    dung) cho toi khi no roi khoi dai (khong con box nao phu o do trong
    khung hien tai) - vi du xe co that di CHAM qua vach trong nhieu khung
    hinh lien tiep van chi bi dem DUNG 1 LAN, nhung 2 xe cat vach cung luc
    o 2 vi tri X khac nhau van duoc dem du ca 2 (khong dua vao track_id nen
    khong co van de trung ID giua 2 xe khac nhau).
    """

    def __init__(self, y_ratio: float, band_px: float = 20.0, cell_px: float = 40.0,
                 miss_tolerance_frames: int = 10):
        self.y_ratio = y_ratio
        self.band_px = band_px
        self.cell_px = cell_px
        # "Grace period": 1 o van duoc coi la "dang bi chiem" toi da bao
        # nhieu khung hinh LIEN TIEP KHONG duoc detect cham vao truoc khi
        # giai phong that su. Truoc day = 0 (giai phong ngay khi mat dau 1
        # khung) - da xac nhan thuc te gay loi: 1 vat the DUNG YEN ngay
        # trong dai quanh vach nhung detection chop tat (confidence dao
        # dong nhe qua tung khung) khien o bi giai phong roi "mo lai" nhieu
        # lan -> dem sai nhieu lan cho CUNG 1 vat the khong he di chuyen. O
        # ~45fps (NPU), 10 khung ~ 0.2s - du hap thu vai khung chop tat lien
        # tiep, van du ngan de khong "nuot" mat 1 xe THAT di qua ngay sau do
        # tai dung vi tri nay.
        self.miss_tolerance_frames = miss_tolerance_frames

        # cell_index -> frame_index gan nhat co box phu len o nay
        self._active_cells = {}
        # cell duoc "cham" (co box phu len) trong khung DANG xu ly - dung
        # de end_frame() biet o nao KHONG con box nao phu nua, can giai
        # phong de sẵn sang dem lan cat vach tiep theo tai vi tri do.
        self._touched_this_frame = set()

    def update(self, centroid_x: float, centroid_y: float, frame_height: float, frame_index: int):
        """Goi 1 lan cho MOI box trong khung hien tai. Tra ve True neu box
        nay vua lam phat sinh 1 lan cat vach MOI (o chua "ban" truoc do,
        VA khong co o lan can dang "ban"), None neu box nam ngoai dai
        quanh vach, o do da dang bi chiem, hoac o lan can dang bi chiem."""
        line_y = frame_height * self.y_ratio
        if abs(centroid_y - line_y) > self.band_px:
            return None

        cell = int(centroid_x // self.cell_px)
        self._touched_this_frame.add(cell)

        already_active = cell in self._active_cells
        # 1 xe DUY NHAT di chuyen hoi cheo (co thanh phan ngang) trong luc
        # con nam trong dai co the truot tu 1 o sang o KE BEN (vd cell 9 ->
        # 10) truoc khi roi han dai - da xac nhan thuc te (dem 2 lan cho 1
        # xe). Kiem tra o LAN CAN (+-1) dang active hay khong - neu co, coi
        # day la CUNG 1 vat the vua truot qua ranh gioi o, KHONG dem them,
        # chi "chuyen" trang thai active sang o moi nay.
        neighbor_active = not already_active and (
            (cell - 1) in self._active_cells or (cell + 1) in self._active_cells
        )
        self._active_cells[cell] = frame_index
        if already_active or neighbor_active:
            return None
        return True

    def end_frame(self, frame_index: int) -> None:
        """Goi 1 lan DUY NHAT sau khi da xu ly het tat ca box trong khung
        hien tai - giai phong o NEU DA mat dau LIEN TUC qua miss_tolerance_
        frames khung hinh (xem giai thich o __init__), de sẵn sang dem lan
        cat vach tiep theo tai chinh vi tri do."""
        stale_cells = [
            c for c, last_seen in self._active_cells.items()
            if frame_index - last_seen > self.miss_tolerance_frames
        ]
        for c in stale_cells:
            self._active_cells.pop(c, None)
        self._touched_this_frame.clear()
