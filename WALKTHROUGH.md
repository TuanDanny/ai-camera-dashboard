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

**Vì giới hạn trên, `view_stream.py` có cờ `--backend {cpu,hailo}`** để
ép chạy CPU khi `main.py` đang giữ NPU (xem cũng lúc mà không tranh
chấp), hoặc chạy `hailo` khi `main.py` không hoạt động (được toàn quyền
NPU, tốc độ cao). `run.sh` khi tự mở `view_stream.py` (ở bước cuối, sau
khi hỏi "Bạn có muốn xem trực tiếp...") **luôn ép `--backend cpu`** vì nó
giả định `main.py` đã chạy trước đó — nên tốc độ xem trực tiếp qua
`run.sh` sẽ chậm hơn (~5-10fps, CPU) so với số liệu FPS thật trên
dashboard (~40-46fps, NPU) — đây là 2 tiến trình độc lập đo 2 thứ khác
nhau, không phải lỗi.

## 5. Đa camera (nhiều luồng RTSP cùng lúc)

Đã kiểm chứng: 2 luồng chia sẻ 1 NPU giữ được throughput tổng gần như
không đổi (round-robin chia tải công bằng, không có overhead đáng kể khi
tranh chấp) — test raw inference: 1 luồng solo 58.6fps, 2 luồng đồng thời
29.5+29.4=58.9fps tổng. Test qua toàn bộ pipeline `main.py` thật (2
station cùng đọc 1 nguồn RTSP để giả lập, khác `station_id`): không
crash, cả 2 đều publish MQTT bình thường, FPS mỗi luồng dao động
24.5-43.4fps.

## 6. Cách bật NPU

Trong `ai-worker/config.yaml`:
```yaml
model:
  backend: hailo
  hailo_hef_path: /usr/share/hailo-models/yolov8s_h8l.hef
```

Yêu cầu máy đã cài `hailo-all` (apt) và venv đã wiring `.pth` trỏ tới
`/usr/lib/python3/dist-packages` (xem chi tiết trong
`ai-worker/config.yaml.example`).
