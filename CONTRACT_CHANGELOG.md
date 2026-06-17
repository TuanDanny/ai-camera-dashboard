# Data Contract Changelog

Tài liệu này ghi lại các thay đổi về Data Contract giữa Tổ Edge và Tổ Server. Bất kỳ thay đổi nào về JSON schema, MQTT topics, hay logic trao đổi dữ liệu đều phải được log vào đây.

## [v1.0.0] - 2026-06-17
### Added
- Khởi tạo Data Contract (Version 1.0).
- Định nghĩa 8 MQTT topics chính: `telemetry`, `heartbeat`, `alert`, `watchdog`, `network_quality`, `snapshot`, `command`, `config`.
- Giao thức QoS 1, Retain rules, và LWT (Last Will & Testament).
- Payload schema dạng JSON cho tất cả các bản tin.
