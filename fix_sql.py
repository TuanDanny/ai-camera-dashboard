import re

with open('d:/SHTP/Server_Plan.md', 'r', encoding='utf-8') as f:
    content = f.read()

sql_blocks = re.findall(r'```sql\n(.*?)\n```', content, re.DOTALL)

with open('d:/SHTP/postgres/init.sql', 'w', encoding='utf-8') as out:
    for block in sql_blocks:
        out.write(block + '\n\n')
    
    out.write("""
-- Insert seed data
INSERT INTO stations (station_id, name, location, status, ip_address, mac_address)
VALUES 
    ('ST-001', 'Trạm Cổng Chính', 'Cổng D2', 'active', '192.168.1.101', '00:1A:2B:3C:4D:5E'),
    ('ST-002', 'Trạm Ngã Tư A', 'Ngã tư D1-D2', 'active', '192.168.1.102', '00:1A:2B:3C:4D:5F'),
    ('ST-003', 'Trạm Đường D3', 'Đường D3', 'maintenance', '192.168.1.103', '00:1A:2B:3C:4D:60')
ON CONFLICT (station_id) DO NOTHING;
""")
