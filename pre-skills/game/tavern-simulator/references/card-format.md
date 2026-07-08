# Character Card & World Book Format Reference

## Character Card Spec (chara_card_v1/v2/v3)

### File Formats
- PNG: JSON embedded in tEXt chunk with key "chara", base64 encoded
- JSON: Direct JSON file

### Key Fields
| Field | Required | Description |
|-------|----------|-------------|
| name | ✅ | Character name |
| description | ✅ | Character info, {{user}}/{{char}} placeholders |
| personality | ✅ | Behavioral guide |
| scenario | 推荐 | Opening scene |
| first_mes | ✅ | First message |
| mes_example | 推荐 | Style template, <START>-delimited |
| system_prompt | 可选 | v2+ override |
| post_history_instructions | 可选 | v2+ constraints |

### World Book Entry Schema
| Field | Meaning |
|-------|---------|
| keys | Trigger keywords |
| content | Lore text |
| position | before_char/after_char/after_example/top/bottom |
| constant | Always included |
| priority | Sort priority |
| selective | Requires secondary key match |