# Walkthrough - Cac thay doi trong phien lam viec nay

Tai lieu nay giai thich lai TOAN BO nhung gi da thay doi trong repo, theo
thu tu thoi gian, de ban co the xem lai va hieu tron ven cau chuyen ma
khong can doc lai tung dong code.

## 1. Xoa SIMULATION MODE - nguon du lieu gia lam ban dashboard

**Van de**: dashboard nhay len vai chuc/vai tram xe moi 10s dù chua co
camera nao huong vao xe that. Nghi ngo do `yolo-cam` (prototype cu) nhung
kiem tra ky thi khong phai - `yolo-cam` chi hien thi "Active tracks", khong
he co logic dem/publish MQTT.

**Nguyen nhan that**: `ai-worker/main.py` co san 1 nhanh SIMULATION MODE -
neu khong ket noi duoc stream that sau vai lan retry, no tu sinh so lieu
gia (`random.uniform(...)`) roi publish len MQTT y het du lieu that.

**Da lam**: xoa han nhanh SIMULATION MODE, thay bang vong lap retry vo han
(khong gioi han lan thu, khong bao gio phat sinh du lieu gia - chi log loi
va thu lai). Don 432+432 dong du lieu gia da lot vao bang `traffic_records`
va `hardware_metrics` (xac dinh chinh xac bang "van tay" toan hoc cua cong
thuc gia lap, vd `detections_raw = total_count * 3`).

## 2. Fix dashboard Grafana bi dung/khong dong bo

**Van de**: panel "Current FPS" dung yen 10.4 dù bieu do FPS ben canh van
chay dung.

**Nguyen nhan**: panel dung `ORDER BY recorded_at DESC LIMIT 1` -
`recorded_at` la timestamp do THIET BI tu gan, co the bi le neu dong ho
thiet bi chua sync NTP luc boot. Mot dong du lieu bi le gio (~23h trong
tuong lai) luon dung dau khi sap xep DESC.

**Da lam**: doi sang `ORDER BY received_at DESC` (thoi diem SERVER nhan
duoc, luon tang dan, khong bao gio le). Ap dung tuong tu cho panel "Overall
AI Accuracy" (`eval_start` -> `created_at`). Dong bo lai `refresh` cho toan
bo dashboard: 10s cho panel lien quan dem xe, 3s cho cac panel con lai.
Them 4 stat panel moi: Total Motorbikes/Cars/Trucks/Buses Today.

## 3. UX chon camera trong `run.sh`

**Van de**: dung IP Webcam (dien thoai) bi lag do phu thuoc mang; muon co
lua chon "cam thang" (CSI hoac USB) de on dinh hon, va muon `run.sh` hoi
truoc khi setup thay vi phai sua tay config.yaml.

**Da lam**: `run.sh` gio hoi tuong tac luc chay: 1) CSI, 2) IP Webcam, 3)
USB Webcam - ghi thang vao `edge-rpi/config.yaml`, dung chung 1
`start_stream.sh` (khong tach script rieng, tranh code trung lap/lech
nhau). IP Webcam co them vong lap: test ket noi that bai thi cho nhap lai
IP. Fix them 1 loi rieng: `rpicam-vid` la ten moi cua `libcamera-vid` tren
Debian Trixie - `start_stream.sh` gio tu do (`command -v rpicam-vid ||
command -v libcamera-vid`).

## 4. Telegram alert bot - hoan thien phan con thieu

**Van de**: code goi Telegram da co tu truoc nhung chua bao gio hoat dong
that.

**Da lam**:
- Fix bug: node function chuan bi `msg.telegram_payload` nhung node gui
  Telegram lai doc `msg.payload` - thieu 1 dong gan `msg.payload =
  msg.telegram_payload`.
- Fix loi `ETELEGRAM: 400 Bad Request: can't parse entities`: dang dung
  `parse_mode: 'Markdown'` (`*bold*`) - ky tu `_` trong ma alert (vd
  `stream_offline`) bi Markdown cu hieu nham la in nghieng. Doi sang
  `parse_mode: 'HTML'` voi the `<b>`.
- Them 3 loai canh bao tu dong that (truoc day chi co 2, khong tu kich
  hoat): mat/phuc hoi stream (`main.py`), CPU qua nhiet, disk day
  (`edge_agent.py`) - chi bao khi CHUYEN muc (binh thuong -> canh bao/khan
  cap hoac nguoc lai) de khong spam.
- Gio hien thi theo VN local time, them link Grafana vao cuoi tin nhan.
- Don sach cac dong test gia da chen vao `device_alerts` luc thu nghiem.

## 5. Chong dem trung xe khi ByteTrack doi ID (`TrackStitcher`)

**Van de**: neu 1 xe bi che khuat lau hon `track_buffer` cua ByteTrack, no
se duoc cap 1 track_id MOI khi xuat hien lai - he thong dem theo track_id
se tinh nham thanh 2 xe dù thuc te chi co 1. Da kiem chung `yolo-cam` (ban
prototype goc) KHONG co van de nay vi no chua bao gio lam dem xe (chi hien
thi "Active tracks" moi frame, khong co logic tich luy).

**Giai phap** (`ai-worker/track_stitcher.py`, class `TrackStitcher`): ghep
1 track_id moi voi track_id cu neu vi tri xuat hien dau tien cua no gan voi
vi tri cuoi cung cua 1 track vua "mat dau" - trong 1 "khoang giua" duoc gioi
han chat che:
- `min_gap_frames=30`: phai >= `track_buffer` cua ByteTrack, de khong
  "giay vao" viec ByteTrack tu no da xu ly tot roi (khong bao gio cuop mot
  track dang con active).
- `max_gap_frames=60`: phai < gia tri cleanup cua `VehicleClassifier`/
  `DirectionCounter` (90 frame), de dam bao khi ghep duoc thi state (class
  da khoa, da qua vach dem chua...) cua track cu van con song.
- `max_distance_px=120`: gioi han khoang cach vi tri.

Duoc goi tu `main.py` truoc tien - moi noi khac deu dung `track_id`
(canonical) tra ve tu day, khong dung `raw_track_id` cua ByteTrack nua.
Test: `ai-worker/local_test/test_track_stitcher.py` (4 kich ban, deu PASS).
Tat ca file test cua `ai-worker` (bao gom 2 file cu
`test_vehicle_classifier.py`/`test_direction_counter.py`) da chuyen vao
`ai-worker/local_test/`.

## 6. Tang toc AI: chuyen tu CPU sang NPU Hailo-8L (13 TOPS)

**Phat hien**: may nay co san 1 NPU Hailo-8L (Raspberry Pi AI HAT+) da cai
day du driver/software (`hailort`, `python3-hailort`, model mau
`yolov8s_h8l.hef` COCO 80 class dung san). Truoc day `ai-worker` chi chay
YOLO tren CPU (`yolov8n_ncnn_model`), toc do 5-17fps tuy tai CPU.

**Da lam**:
- `ai-worker/hailo_yolo.py` (moi): class `HailoYolo` bao quanh HailoRT, doc
  model `yolov8s_h8l.hef` (co san NMS-by-class ngay tren chip), tu lam
  letterbox preprocess + denormalize ket qua ve toa do pixel that - da
  kiem chung bang anh that (dem dung 11/11 nguoi trong 1 anh mau).
- `ai-worker/tracker_hailo/` (moi): vendor nguyen ban ByteTrack chuan (tu
  repo Hailo chinh thuc), vi backend Hailo khong di qua pipeline
  tracking tich hop cua ultralytics nhu backend CPU.
- `ai-worker/main.py`: them `model.backend: cpu | hailo` trong
  `config.yaml`. Tach rieng phan "lay detection moi frame" (2 ham
  `cpu_frame_source()`/`hailo_frame_source()`) khoi phan dem xe/publish
  MQTT dung chung (`apply_detections()`) - logic dem xe/TrackStitcher/
  VehicleClassifier khong doi gi ca, chi doi nguon detection dau vao.
- `ai-worker/view_stream.py` (cua so debug xem truc tiep): cung duoc nang
  cap dung chung logic backend nay (xem muc 8 ben duoi).

**Ket qua do thuc te**: **5-17fps (CPU) -> 40-46fps (NPU)**, ~21-24ms/frame
inference, gan nhu khong ton CPU.

**Luu y ky thuat**: `hailo_platform`/`picamera2` chi cai duoc qua apt
(khong co tren PyPI) - ca `ai-worker/.venv` va `ai-worker/.venv-view` can 1
lan setup them 1 file `.pth` tro sang `/usr/lib/python3/dist-packages` de
2 venv nay thay duoc goi he thong. Da ghi chu chi tiet lenh nay trong
`ai-worker/config.yaml.example`.

## 7. Phat hien va tat 2 systemd service cu gay xung dot

**Van de**: FPS tut xuong con 1.5fps du da xong tich hop NPU.

**Nguyen nhan**: may nay co 2 systemd service TU DONG chay lai (moi khi bi
kill se tu bat lai sau 5s):
- `shtp_camera.service`: chay `yolo_cam_live.py` (prototype cu trong thu
  muc `yolo-cam`) - an ~245% CPU vo ich, khong lien quan gi den
  `ai-camera-dashboard` nua.
- `shtp_agent.service`: chay nham `edge_agent.py` cua `ai-camera-dashboard`
  nhung dung sai venv (`yolo-cam/.venv`) - chay song song, xung dot voi
  tien trinh `run.sh` tu tay khoi dong (2 bo `edge_agent.py`/`ffmpeg` cung
  tranh `/dev/video0` va cong RTSP).

**Da lam**: `systemctl stop` + `systemctl disable` ca 2 service nay. Sau
khi tat, FPS CPU backend tang tro lai 5-17fps binh thuong (truoc khi tiep
tuc chuyen sang NPU o muc 6).

## 8. `view_stream.py` (cua so debug) cham (6-7fps) - da tang toc bang NPU

**Nguyen nhan**: `view_stream.py` hardcode `device='cpu'`, tu chay 1
pipeline YOLO CPU rieng - canh tranh CPU voi `main.py` (dù `main.py` da
chuyen sang NPU, `view_stream.py` van chua biet gi ve backend moi).

**Da lam**: `view_stream.py` gio doc `config.yaml`'s `model.backend` giong
`main.py` - neu `hailo`, dung lai `HailoYolo` + `BYTETracker` (vendor
trong `tracker_hailo/`) thay vi `model.track(device='cpu')`.

**Gioi han quan trong da phat hien**: Hailo-8L o day chi co **1 thiet bi
vat ly**, KHONG cho 2 TIEN TRINH (process) OS rieng biet cung mo VDevice
mot luc (loi `HAILO_OUT_OF_PHYSICAL_DEVICES`). Neu `main.py` dang chay
backend `hailo`, chay them `view_stream.py` backend `hailo` cung luc se
loi - phai dung 1 trong 2 truoc. `view_stream.py` da duoc them bat loi nay
va bao thong bao ro rang thay vi traceback kho hieu.
`ai-worker/.venv-view` (venv rieng cho cua so debug, can opencv GUI) cung
duoc them file `.pth` + cai `lap`/`cython_bbox`/`scipy` giong
`ai-worker/.venv`.

## 9. Camera bi toi - khong phai do anh sang, do sai dinh dang capture

**Trieu chung**: hinh camera (USB webcam "Xitech USB Camera") den thui/mo
khi xem qua `start_stream.sh`.

**Chan doan sai luc dau**: tuong do thieu sang, da thu tang
`brightness`/`gamma`/`backlight_compensation` qua `v4l2-ctl` - co cai
thien (den -> xam) nhung van mo/khong ro.

**Nguyen nhan that**: camera nay ho tro 25-30fps o do phan giai 720p
**chi khi dung dinh dang MJPG (nen)** - dinh dang YUYV (khong nen) chi dat
~10fps o cung do phan giai. Lenh ffmpeg trong `start_stream.sh` khong ep
dinh dang input, nen co the roi vao YUYV trong khi van yeu cau 25fps ->
camera khong dap ung kip, sinh ra hinh hong/toi. Nguoi dung phat hien: camera
binh thuong khi khong di qua script nay - dau moi giup xac dinh dung
huong (loi o cach script goi camera, khong phai camera hong).

**Da lam**: them `-input_format mjpeg` vao ca 2 lenh ffmpeg trong nhanh
`webcam` cua `start_stream.sh`. Da test lai: hinh anh ro net, du sang ngay
voi cai dat v4l2 mac dinh - khong can chinh `brightness`/`gamma` nua (da
revert cac gia tri da thu truoc do). Van giu lai co che tuy chon
`brightness`/`gamma`/`backlight_compensation` trong `config.yaml.example`
(dang comment san) cho truong hop 1 camera khac thuc su can chinh do sang.

## Danh sach file chinh da doi

| File | Thay doi |
|---|---|
| `ai-worker/main.py` | Xoa SIMULATION MODE, them TrackStitcher, them backend Hailo |
| `ai-worker/hailo_yolo.py` | Moi - wrap NPU Hailo-8L |
| `ai-worker/track_stitcher.py` | Moi - chong dem trung xe |
| `ai-worker/tracker_hailo/` | Moi - vendor ByteTrack cho backend Hailo |
| `ai-worker/view_stream.py` | Ho tro ca 2 backend cpu/hailo |
| `ai-worker/local_test/` | Tat ca file test (bao gom 2 file cu da chuyen vao) |
| `edge-rpi/start_stream.sh` | Chon CSI/webcam/ip_webcam, fix rpicam-vid, fix -input_format mjpeg |
| `run.sh` | Hoi tuong tac chon camera |
| `grafana/dashboards/*.json` | Fix panel dung, dong bo refresh, them stat panel |
| `generate_flows.py` | Fix Telegram bot (payload, parse_mode, format tin nhan) |
| `edge-rpi/edge_agent.py` | Them canh bao CPU/disk tu dong |
