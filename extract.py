import json

with open('C:/Users/tuand/.gemini/antigravity/brain/ef1c54c5-0054-4d47-9d4c-9c9f483165f1/.system_generated/logs/transcript_full.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        try:
            data = json.loads(line)
            if data.get('type') == 'PLANNER_RESPONSE' and 'tool_calls' in data:
                for tc in data['tool_calls']:
                    if tc['name'] == 'send_message':
                        msg = tc['args']['Message']
                        with open('C:/Users/tuand/.gemini/antigravity/brain/39c41ea8-77f7-459b-b9c3-36dfc548fec3/qa_report_full.md', 'w', encoding='utf-8') as out:
                            out.write(msg)
        except Exception:
            pass
