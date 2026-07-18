var p = msg.payload;
msg.query = `INSERT INTO device_alerts (
    station_id, alert_at, severity, code, message, details
) VALUES ($1, to_timestamp($2), $3, $4, $5, $6)`;
msg.params = [p.station_id, p.timestamp, p.severity, p.code, p.message, JSON.stringify(p.details || {})];

// Cac ma "da phuc hoi" van co severity=info (khong phai su co) nhung van
// dang gui Telegram de nguoi van hanh biet su co da het, khong chi im lang.
var recoveryCodes = ['stream_recovered', 'cpu_temp_normal', 'disk_usage_normal'];
var sendToTelegram = p.severity === 'critical' || p.severity === 'warning' || recoveryCodes.includes(p.code);

if (sendToTelegram) {
    var icon = p.severity === 'critical' ? '🚨' : (p.severity === 'warning' ? '⚠️' : '✅');
    var timeStr = new Date(p.timestamp * 1000).toLocaleString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh' });
    // HTML thay vi Markdown: cac ma alert co dau "_" (stream_offline,
    // cpu_temp_warning...) khien Markdown legacy cua Telegram parse loi vi no
    // coi "_" la ky tu dac biet (in nghieng) - HTML khong co van de nay.
    var content = `${icon} <b>${p.severity.toUpperCase()}</b>\n` +
        `📍 Trạm: ${p.station_id}\n` +
        `🕒 ${timeStr}\n` +
        `📋 Mã: ${p.code}\n` +
        `📝 ${p.message}\n` +
        `🔗 ${env.get("GRAFANA_URL")}`;
    // telegram sender doc tu msg.payload, nen phai ghi de payload (khong chi
    // mot field rieng) truoc khi no toi node do.
    msg.telegram_payload = {
        chatId: env.get("TELEGRAM_CHAT_ID"),
        type: 'message',
        content: content,
        options: { parse_mode: 'HTML' }
    };
    msg.payload = msg.telegram_payload;
}
return msg;