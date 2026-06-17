-- ============================================================
-- File: init.sql
-- Mô tả: Khởi tạo toàn bộ schema cho hệ thống SHTP Traffic
-- Phiên bản: 3.0
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- -----------------------------------------------------------
-- 1. STATIONS
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS stations (
    station_id          VARCHAR(50)   PRIMARY KEY,
    location_name       VARCHAR(255)  NOT NULL,
    latitude            DECIMAL(9,6),
    longitude           DECIMAL(9,6),
    description         TEXT,
    firmware_version    VARCHAR(50),
    status              VARCHAR(20)   NOT NULL DEFAULT 'inactive',
    telemetry_interval_s INT          NOT NULL DEFAULT 60,
    last_seen_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT chk_status CHECK (status IN ('active','inactive','offline','maintenance'))
);

COMMENT ON TABLE stations IS 'Danh sách các trạm camera AI biên';

-- -----------------------------------------------------------
-- 2. TRAFFIC_RECORDS
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS traffic_records (
    id                  BIGSERIAL     PRIMARY KEY,
    station_id          VARCHAR(50)   NOT NULL REFERENCES stations(station_id) ON DELETE CASCADE,
    recorded_at         TIMESTAMPTZ   NOT NULL,
    seq                 INT,
    interval_seconds    INT           NOT NULL DEFAULT 60,
    motorbike_count     INT           NOT NULL DEFAULT 0 CHECK (motorbike_count >= 0),
    car_count           INT           NOT NULL DEFAULT 0 CHECK (car_count >= 0),
    truck_count         INT           NOT NULL DEFAULT 0 CHECK (truck_count >= 0),
    bus_count           INT           NOT NULL DEFAULT 0 CHECK (bus_count >= 0),
    bicycle_count       INT           NOT NULL DEFAULT 0 CHECK (bicycle_count >= 0),
    unknown_count       INT           NOT NULL DEFAULT 0 CHECK (unknown_count >= 0),
    total_count         INT           NOT NULL DEFAULT 0 CHECK (total_count >= 0),
    inbound_count       INT           DEFAULT 0,
    outbound_count      INT           DEFAULT 0,
    avg_confidence      NUMERIC(4,3)  CHECK (avg_confidence >= 0 AND avg_confidence <= 1),
    min_confidence      NUMERIC(4,3)  CHECK (min_confidence >= 0 AND min_confidence <= 1),
    detections_raw      INT           DEFAULT 0,
    detections_filtered INT           DEFAULT 0,
    lighting_condition  VARCHAR(10),
    received_at         TIMESTAMPTZ   NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_traffic_station_time ON traffic_records(station_id, recorded_at DESC);
CREATE INDEX idx_traffic_recorded_at  ON traffic_records(recorded_at DESC);
CREATE INDEX idx_traffic_lighting     ON traffic_records(lighting_condition, recorded_at DESC);

-- -----------------------------------------------------------
-- 3. HARDWARE_METRICS
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS hardware_metrics (
    id                      BIGSERIAL   PRIMARY KEY,
    station_id              VARCHAR(50) NOT NULL REFERENCES stations(station_id) ON DELETE CASCADE,
    recorded_at             TIMESTAMPTZ NOT NULL,
    uptime_seconds          INT,
    cpu_temp_c              NUMERIC(5,2),
    enclosure_temp_c        NUMERIC(5,2),
    input_voltage_v         NUMERIC(5,2),
    signal_rssi_dbm         INT,
    signal_quality_pct      INT,
    free_memory_kb          INT,
    disk_usage_pct          INT,
    fps                     NUMERIC(5,2),
    inference_ms            INT,
    watchdog_luckfox_ok     BOOLEAN,
    watchdog_esp32_ok       BOOLEAN,
    camera_status           VARCHAR(20),
    last_reboot_reason      VARCHAR(20),
    received_at             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_hw_station_time ON hardware_metrics(station_id, recorded_at DESC);

-- -----------------------------------------------------------
-- 4. DEVICE_ALERTS
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS device_alerts (
    id                  BIGSERIAL     PRIMARY KEY,
    station_id          VARCHAR(50)   NOT NULL REFERENCES stations(station_id) ON DELETE CASCADE,
    alert_at            TIMESTAMPTZ   NOT NULL,
    severity            VARCHAR(20)   NOT NULL,
    code                VARCHAR(50)   NOT NULL,
    message             TEXT,
    details             JSONB,
    acknowledged        BOOLEAN       NOT NULL DEFAULT false,
    acknowledged_at     TIMESTAMPTZ,
    received_at         TIMESTAMPTZ   NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_severity CHECK (severity IN ('info','warning','critical'))
);

CREATE INDEX idx_alerts_station_time    ON device_alerts(station_id, alert_at DESC);
CREATE INDEX idx_alerts_unacknowledged  ON device_alerts(acknowledged) WHERE acknowledged = false;
CREATE INDEX idx_alerts_severity        ON device_alerts(severity, alert_at DESC);

-- -----------------------------------------------------------
-- 5. WATCHDOG_EVENTS
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS watchdog_events (
    id                      BIGSERIAL     PRIMARY KEY,
    station_id              VARCHAR(50)   NOT NULL REFERENCES stations(station_id) ON DELETE CASCADE,
    event_at                TIMESTAMPTZ   NOT NULL,
    event_type              VARCHAR(50)   NOT NULL,
    reason                  VARCHAR(100),
    details                 JSONB,
    uptime_before_reset_s   INT,
    reset_count_since_boot  INT,
    received_at             TIMESTAMPTZ   NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_event_type CHECK (event_type IN (
        'luckfox_reset_by_esp32',
        'esp32_reset_by_luckfox',
        'hw_watchdog_triggered',
        'power_cycle_detected',
        'manual_reset'
    ))
);

CREATE INDEX idx_watchdog_station_time ON watchdog_events(station_id, event_at DESC);
CREATE INDEX idx_watchdog_event_type   ON watchdog_events(event_type, event_at DESC);

COMMENT ON TABLE watchdog_events IS 'Nhật ký sự kiện Watchdog reset (ESP32↔Luckfox chéo, IC cứng)';

-- -----------------------------------------------------------
-- 6. NETWORK_QUALITY
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS network_quality (
    id                      BIGSERIAL     PRIMARY KEY,
    station_id              VARCHAR(50)   NOT NULL REFERENCES stations(station_id) ON DELETE CASCADE,
    recorded_at             TIMESTAMPTZ   NOT NULL,
    operator                VARCHAR(50),
    technology              VARCHAR(20),
    band                    VARCHAR(10),
    rssi_dbm                INT,
    rsrp_dbm                INT,
    rsrq_db                 INT,
    sinr_db                 NUMERIC(5,2),
    latency_ms              INT,
    packet_loss_pct         NUMERIC(5,2),
    reconnect_count         INT           DEFAULT 0,
    bytes_sent              BIGINT        DEFAULT 0,
    bytes_received          BIGINT        DEFAULT 0,
    mqtt_reconnect_count    INT           DEFAULT 0,
    received_at             TIMESTAMPTZ   NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_nq_station_time ON network_quality(station_id, recorded_at DESC);

COMMENT ON TABLE network_quality IS 'Chất lượng đường truyền 4G của trạm biên';

-- -----------------------------------------------------------
-- 7. SNAPSHOTS
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS snapshots (
    id                  BIGSERIAL     PRIMARY KEY,
    station_id          VARCHAR(50)   NOT NULL REFERENCES stations(station_id) ON DELETE CASCADE,
    captured_at         TIMESTAMPTZ   NOT NULL,
    format              VARCHAR(10)   NOT NULL DEFAULT 'jpeg',
    resolution          VARCHAR(20),
    size_bytes          INT,
    lighting_condition  VARCHAR(10),
    file_path           TEXT          NOT NULL,
    received_at         TIMESTAMPTZ   NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_snapshots_station_time ON snapshots(station_id, captured_at DESC);

COMMENT ON TABLE snapshots IS 'Metadata ảnh chụp từ camera biên (file lưu trên volume)';

-- -----------------------------------------------------------
-- 8. COMMAND_LOG
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS command_log (
    id              BIGSERIAL     PRIMARY KEY,
    station_id      VARCHAR(50)   NOT NULL REFERENCES stations(station_id) ON DELETE CASCADE,
    command_id      VARCHAR(100)  UNIQUE NOT NULL,
    command         VARCHAR(100)  NOT NULL,
    params          JSONB,
    issued_at       TIMESTAMPTZ   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status          VARCHAR(20)   NOT NULL DEFAULT 'pending',
    acked_at        TIMESTAMPTZ,

    CONSTRAINT chk_cmd_status CHECK (status IN ('pending','acked','failed','expired'))
);

COMMENT ON TABLE command_log IS 'Nhật ký các lệnh điều khiển gửi từ Server xuống trạm biên';

-- -----------------------------------------------------------
-- 9. ACCURACY_EVALUATIONS
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS accuracy_evaluations (
    id                      BIGSERIAL     PRIMARY KEY,
    station_id              VARCHAR(50)   NOT NULL REFERENCES stations(station_id) ON DELETE CASCADE,
    eval_start              TIMESTAMPTZ   NOT NULL,
    eval_end                TIMESTAMPTZ   NOT NULL,
    lighting_condition      VARCHAR(10)   NOT NULL,
    evaluator_name          VARCHAR(100),

    -- Số liệu đếm thủ công (Ground Truth)
    manual_motorbike        INT           NOT NULL DEFAULT 0,
    manual_car              INT           NOT NULL DEFAULT 0,
    manual_truck            INT           NOT NULL DEFAULT 0,
    manual_bus              INT           NOT NULL DEFAULT 0,
    manual_bicycle          INT           NOT NULL DEFAULT 0,
    manual_total            INT           NOT NULL DEFAULT 0,

    -- Số liệu AI trong cùng khoảng thời gian (tự động truy vấn từ traffic_records)
    ai_motorbike            INT           NOT NULL DEFAULT 0,
    ai_car                  INT           NOT NULL DEFAULT 0,
    ai_truck                INT           NOT NULL DEFAULT 0,
    ai_bus                  INT           NOT NULL DEFAULT 0,
    ai_bicycle              INT           NOT NULL DEFAULT 0,
    ai_total                INT           NOT NULL DEFAULT 0,

    -- Kết quả đánh giá
    accuracy_overall_pct    NUMERIC(5,2),
    accuracy_motorbike_pct  NUMERIC(5,2),
    accuracy_car_pct        NUMERIC(5,2),
    accuracy_truck_pct      NUMERIC(5,2),
    accuracy_bus_pct        NUMERIC(5,2),

    notes                   TEXT,
    created_at              TIMESTAMPTZ   NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_lighting CHECK (lighting_condition IN ('day','night','dawn','dusk')),
    CONSTRAINT chk_eval_range CHECK (eval_end > eval_start)
);

CREATE INDEX idx_accuracy_station ON accuracy_evaluations(station_id, eval_start DESC);
CREATE INDEX idx_accuracy_lighting ON accuracy_evaluations(lighting_condition);

COMMENT ON TABLE accuracy_evaluations IS 'Kết quả đánh giá độ chính xác AI so với đếm thủ công (ban ngày vs ban đêm)';

-- -----------------------------------------------------------
-- 10. SEED DATA
-- -----------------------------------------------------------
INSERT INTO stations (station_id, location_name, latitude, longitude, description, status)
VALUES 
    ('ST-001', 'Ngã tư Xa lộ Hà Nội - Phạm Văn Đồng', 10.8487, 106.7710, 'Trạm demo #1 - Lab SHTP', 'active'),
    ('ST-002', 'Vòng xoay Mỹ Thuỷ', 10.7690, 106.7530, 'Trạm demo #2', 'inactive'),
    ('ST-003', 'Cầu Sài Gòn hướng vào Q1', 10.7930, 106.7190, 'Trạm demo #3', 'inactive')
ON CONFLICT (station_id) DO NOTHING;

-- Insert traffic record
INSERT INTO traffic_records 
    (station_id, recorded_at, seq, interval_seconds,
     motorbike_count, car_count, truck_count, bus_count, 
     bicycle_count, unknown_count, total_count,
     inbound_count, outbound_count, avg_confidence, min_confidence,
     detections_raw, detections_filtered, lighting_condition)
VALUES 
    ($1, to_timestamp($2), $3, $4,
     $5, $6, $7, $8,
     $9, $10, $11,
     $12, $13, $14, $15,
     $16, $17, $18);

-- Insert hardware metrics
INSERT INTO hardware_metrics 
    (station_id, recorded_at, uptime_seconds, cpu_temp_c, enclosure_temp_c,
     input_voltage_v, signal_rssi_dbm, signal_quality_pct,
     free_memory_kb, disk_usage_pct, fps, inference_ms,
     watchdog_luckfox_ok, watchdog_esp32_ok, camera_status, last_reboot_reason)
VALUES 
    ($1, to_timestamp($2), $3, $4, $5,
     $6, $7, $8,
     $9, $10, $11, $12,
     $13, $14, $15, $16);

-- Update station last_seen
UPDATE stations 
SET last_seen_at = CURRENT_TIMESTAMP, 
    status = 'active',
    updated_at = CURRENT_TIMESTAMP
WHERE station_id = $1;

-- Insert watchdog event
INSERT INTO watchdog_events
    (station_id, event_at, event_type, reason, details,
     uptime_before_reset_s, reset_count_since_boot)
VALUES ($1, to_timestamp($2), $3, $4, $5, $6, $7);

-- Insert network quality
INSERT INTO network_quality
    (station_id, recorded_at, operator, technology, band,
     rssi_dbm, rsrp_dbm, rsrq_db, sinr_db,
     latency_ms, packet_loss_pct, reconnect_count,
     bytes_sent, bytes_received, mqtt_reconnect_count)
VALUES ($1, to_timestamp($2), $3, $4, $5,
        $6, $7, $8, $9,
        $10, $11, $12, $13, $14, $15);


-- Insert seed data
INSERT INTO stations (station_id, name, location, status, ip_address, mac_address)
VALUES 
    ('ST-001', 'Trạm Cổng Chính', 'Cổng D2', 'active', '192.168.1.101', '00:1A:2B:3C:4D:5E'),
    ('ST-002', 'Trạm Ngã Tư A', 'Ngã tư D1-D2', 'active', '192.168.1.102', '00:1A:2B:3C:4D:5F'),
    ('ST-003', 'Trạm Đường D3', 'Đường D3', 'maintenance', '192.168.1.103', '00:1A:2B:3C:4D:60')
ON CONFLICT (station_id) DO NOTHING;
