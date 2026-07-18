# Walkthrough: Tích hợp NPU Hailo-8L cho AI Worker

Tài liệu này giải thích kiến trúc xử lý AI hiện tại của `ai-worker/` — đặc
biệt là phần tích hợp NPU Hailo-8L (13 TOPS) mới, viết lại từ đầu với
kiến trúc rõ ràng hơn so với lần tích hợp thử nghiệm trước (còn lưu trên
nhánh `backup_npu`, không dùng trực tiếp).

## 1. Tổng quan pipeline

```
Camera → ffmpeg → MediaMTX (docker) → main.py [xử lý AI] → MQTT (docker)
                                                              → Node-RED → Postgres → Grafana
```

`main.py` là nơi duy nhất tốn tài nguyên tính toán nặng — mọi phần còn lại
(Docker, MQTT, Node-RED, Postgres, Grafana) không đổi gì bất kể dùng CPU
hay NPU.

## 2. Hai backend, chọn qua config

`ai-worker/config.yaml`'s `model.backend` quyết định `main.py` dùng gì:

- **`cpu`** (mặc định): chạy qua `ultralytics` (`model.track()`), model
  `yolov8n_ncnn_model` — nhẹ, không cần phần cứng đặc biệt, nhưng chậm
  (~5-17fps tùy tải máy trên Raspberry Pi 4 core).
- **`hailo`**: chạy qua NPU Hailo-8L, model `yolov8s_h8l.hef` (đã compile
  sẵn NMS-by-class) — đo thực tế đạt **~40-46fps/camera** (~21-24ms mỗi
  frame), nhanh hơn CPU 4-8 lần.

Cả 2 backend cùng cung cấp 1 interface giống hệt nhau ra bên ngoài:
`(frame, boxes, inference_ms, fps)` với `boxes` là list
`(track_id, class_id, confidence, x1, y1, x2, y2)` — nhờ vậy `main.py` và
`view_stream.py` chỉ cần đổi **1 dòng chọn hàm nguồn**, không phải viết
lại logic đếm xe/publish MQTT khi đổi backend.

## 3. Kiến trúc phía NPU (`ai-worker/pipeline/`)

```
hailo_source.py     → khởi tạo Hailo() an toàn (xem mục 4 - giới hạn quan trọng)
hailo_detector.py   → tiền xử lý (letterbox) + inference + giải mã NMS-by-class
hailo_tracker.py    → ClassAwareTracker: tracking THEO TỪNG LỚP xe
hailo_frame_source.py → ghép 3 file trên thành 1 generator bất đồng bộ
```

### Khác biệt quan trọng so với lần tích hợp thử nghiệm trước (`backup_npu`)

**(a) Tracking theo lớp, không còn "đoán lại class sau khi tracking".**
Model Hailo trả kết quả theo 80 mảng riêng (1 lớp COCO/mảng), nhưng thư
viện tracking (ByteTrack) chỉ nhận `[x,y,x,y,score]` — không giữ nhãn
lớp. Bản cũ giải quyết bằng cách tracking xong rồi so IoU lại với
detection gốc để "đoán" track thuộc lớp nào — vừa lãng phí (tính IoU 2
lần) vừa dễ gán nhầm khi 2 loại xe khác nhau đứng gần nhau. Bản mới dùng
**1 `BYTETracker` riêng cho mỗi lớp xe** (`ClassAwareTracker`) — tracker
của "car" không bao giờ thấy box của "motorbike", nên không thể ghép
nhầm ID giữa 2 lớp. Track ID gộp lại duy nhất bằng công thức
`class_id * 100_000 + track_id_rieng`. Đã kiểm chứng qua video giao thông
thật: 0/27 và 0/19 track bị đổi nhãn qua 2 lần test độc lập.

**(b) Kiến trúc bất đồng bộ producer-consumer, tách rời tốc độ NPU khỏi
tốc độ CPU tiêu thụ.** `hailo_frame_source()` chạy 1 thread nền
(producer) đọc frame → NPU → tracking → đóng gói kết quả → đẩy vào 1
buffer nội bộ (`queue.Queue`), không bao giờ chờ bên tiêu thụ. Bên gọi
(consumer — vòng lặp chính của `main.py`/`view_stream.py`) chỉ lấy khung
**mới nhất** từ buffer, không bao giờ chờ NPU. 2 chính sách buffer khác
nhau theo mục đích:
- `view_stream.py` (chỉ xem): `buffer_size=1`, ghi đè khung cũ ngay khi có
  khung mới — ưu tiên tuyệt đối tốc độ hiển thị, mất khung không sao.
- `main.py` (đếm xe thật): `buffer_size=4` — lớp đệm an toàn chống mất
  khung khi CPU khựng ngắn bất thường, kèm `on_frame_dropped` callback để
  đo thực tế có bao giờ rớt khung không (đo thật: **0 lần rớt trong 3
  phút chạy liên tục**).

## 4. Giới hạn phần cứng quan trọng — 1 NPU vật lý

Đã phát hiện qua thử nghiệm thực tế (không phải suy đoán lý thuyết):

- **Trong CÙNG 1 tiến trình OS**: nhiều `Hailo()` instance chia sẻ được 1
  NPU (round-robin scheduling) — **nhưng chỉ khi TẤT CẢ được khởi tạo từ
  CÙNG 1 thread** (khuyến nghị: main thread, trước khi mở thread riêng
  cho từng camera). 2 thread khác nhau tự khởi tạo riêng — dù có khóa
  đồng bộ hóa — vẫn gây lỗi native `Resource deadlock avoided`. Đây là lý
  do `main.py`'s `main()` tạo hết `Hailo()` cho mọi camera TRƯỚC khi mở
  thread xử lý, rồi mới truyền instance vào từng thread.
- **Giữa 2 tiến trình OS khác nhau** (vd `main.py` và `view_stream.py`
  chạy `python3` riêng): KHÔNG chia sẻ được NPU — tiến trình thứ 2 sẽ gặp
  lỗi `HAILO_OUT_OF_PHYSICAL_DEVICES`. Không có cách sửa bằng code (giới
  hạn phần cứng thật), chỉ có thể báo lỗi rõ ràng và hướng dẫn dùng CPU
  thay thế.

**Vì giới hạn trên, `view_stream.py` có cờ `--backend {cpu,hailo,relay}`**
— `relay` (mặc định khi `run.sh` tự mở) không đụng tới NPU/CPU YOLO gì cả,
chỉ nhận lại kết quả `main.py` đã xử lý sẵn qua 1 socket nội bộ (xem mục
7) nên không bao giờ tranh chấp NPU với `main.py`, đồng thời FPS hiển thị
gần với FPS thật của `main.py` hơn nhiều so với việc tự chạy lại YOLO trên
CPU. `cpu`/`hailo` vẫn còn để tự chạy YOLO riêng khi cần (vd `main.py`
chưa chạy, hoặc muốn debug riêng qua chính NPU sau khi tắt `main.py`).

## 5. Đa camera (nhiều luồng RTSP cùng lúc)

Đã kiểm chứng: 2 luồng chia sẻ 1 NPU giữ được throughput tổng gần như
không đổi (round-robin chia tải công bằng, không có overhead đáng kể khi
tranh chấp) — test raw inference: 1 luồng solo 58.6fps, 2 luồng đồng thời
29.5+29.4=58.9fps tổng. Test qua toàn bộ pipeline `main.py` thật (2
station cùng đọc 1 nguồn RTSP để giả lập, khác `station_id`): không
crash, cả 2 đều publish MQTT bình thường, FPS mỗi luồng dao động
24.5-43.4fps.

## 6. Chia sẻ kết quả NPU cho `view_stream.py` qua socket (không chạy 2 lần YOLO)

Trước đây `view_stream.py` tự chạy YOLO riêng (CPU) để xem trực tiếp,
song song với `main.py` đang chạy YOLO/NPU thật cho dashboard — lãng phí
tài nguyên và khiến FPS xem (~5-10fps CPU) lệch xa FPS thật
(~40-46fps NPU), dễ gây hiểu lầm là NPU chậm.

`ai-worker/pipeline/frame_broadcast.py` giải quyết việc này bằng 1 Unix
domain socket nội bộ (`/tmp/shtp_ai_worker_view.sock`):

- **`FrameBroadcaster`** (chạy trong `main.py`): sau mỗi khung xử lý xong
  (bất kể `main.py` đang dùng backend `cpu` hay `hailo`), gọi
  `publish(station_id, frame, boxes, inference_ms, fps)` — chỉ ghi đè 1
  biến "hộp thư 1 ngăn" (cực nhanh, không bao giờ làm chậm vòng lặp xử lý
  chính). Việc mã hoá JPEG + gửi qua socket (chậm hơn) chạy ở 1 thread nền
  riêng (`_sender_loop`). Giao thức: 2 phần length-prefixed (4 byte đầu
  ghi độ dài) — JSON metadata nhỏ (không có ảnh) rồi tới khối JPEG nhị
  phân thô (không dùng base64 — từng thử base64 nhưng làm ảnh phình thêm
  ~33% dung lượng mà không giải quyết được gốc vấn đề tốc độ, xem
  `npu_plan.md`). Client kết nối vào nhưng không đọc (treo/GUI đứng) được
  xử lý bằng `settimeout()` trên kết nối để không làm `sendall()` chặn vô
  thời hạn.
- **`socket_frame_source()`** (dùng trong `view_stream.py` khi
  `--backend relay`): generator phía client, kết nối vào socket trên,
  nhận + giải mã, `yield (frame, boxes, inference_ms, fps)` — **cùng hình
  dạng interface** với `cpu_frame_source()`/`hailo_frame_source()` nên
  vòng lặp vẽ/hiển thị trong `view_stream.py` dùng chung, không cần biết
  đang ở chế độ nào. Chỉ hỗ trợ 1 client tại 1 thời điểm (đúng nhu cầu
  thực tế — chỉ 1 người xem debug).

**Giới hạn tốc độ đã đo thật**: FPS hiển thị qua relay đạt ổn định
~20fps (không phụ thuộc base64 hay không — đã kiểm chứng cả 2 trường
hợp), thấp hơn FPS thật của NPU (~40-46fps). Nguyên nhân là **tranh chấp
CPU tổng thể trên Raspberry Pi 4 core** (giữa `ffmpeg` mã hoá camera,
`main.py`'s pipeline NPU, và thread mã hoá/gửi JPEG), không phải giới hạn
của giao thức — đường ống IPC tự nó đo được tới ~63fps khi không có
`main.py` thật chạy song song. ~20fps vẫn đủ mượt cho mục đích xem debug
trực tiếp; số đếm xe thật (MQTT) hoàn toàn không đi qua đường này nên
không bị ảnh hưởng.

## 7. Cách bật NPU

Trong `ai-worker/config.yaml`:
```yaml
model:
  backend: hailo
  hailo_hef_path: /usr/share/hailo-models/yolov8s_h8l.hef
```

Yêu cầu máy đã cài `hailo-all` (apt) và venv đã wiring `.pth` trỏ tới
`/usr/lib/python3/dist-packages` (xem chi tiết trong
`ai-worker/config.yaml.example`).
