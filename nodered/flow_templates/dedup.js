var cache = context.get('dedup_cache') || {};
var p = msg.payload;
var key = p.station_id + '_' + (p.seq || p.timestamp);
var now = Date.now();
for (var k in cache) {
    if (now - cache[k] > 300000) delete cache[k];
}
if (cache[key]) { return null; }
cache[key] = now;
context.set('dedup_cache', cache);
return msg;