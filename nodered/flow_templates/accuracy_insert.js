var p = msg.payload;
msg.query = `INSERT INTO accuracy_evaluations (
    station_id, eval_start, eval_end, lighting_condition, evaluator_name,
    manual_motorbike, manual_car, manual_truck, manual_bus, manual_bicycle, manual_total,
    ai_motorbike, ai_car, ai_truck, ai_bus, ai_bicycle, ai_total,
    accuracy_overall_pct, accuracy_motorbike_pct, accuracy_car_pct, accuracy_truck_pct, accuracy_bus_pct,
    notes
) VALUES (
    $1, to_timestamp($2), to_timestamp($3), $4, $5,
    $6, $7, $8, $9, $10, $11,
    $12, $13, $14, $15, $16, $17,
    $18, $19, $20, $21, $22,
    $23
)`;
msg.params = [
    p.station_id, p.eval_start, p.eval_end, p.lighting_condition, p.evaluator_name,
    p.manual_motorbike, p.manual_car, p.manual_truck, p.manual_bus, p.manual_bicycle, p.manual_total,
    p.ai_motorbike, p.ai_car, p.ai_truck, p.ai_bus, p.ai_bicycle, p.ai_total,
    p.accuracy_overall_pct, p.accuracy_motorbike_pct, p.accuracy_car_pct, p.accuracy_truck_pct, p.accuracy_bus_pct,
    p.notes
];
return msg;