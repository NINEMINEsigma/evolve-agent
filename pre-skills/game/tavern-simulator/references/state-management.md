# Session State Management

## File Structure
```
tavern-session/
├── session.json     # Metadata, character state
├── character.json   # Normalized character card
├── world-book.json  # World book (if loaded)
└── chat-log.md      # Conversation history
```

## session.json Schema
{
  "session_id": "...",
  "created_at": "...",
  "character_name": "...",
  "user_name": "...",
  "status": "active",
  "message_count": N,
  "character_state": {
    "mood": "...",
    "relationship_level": 0-10,
    "flags": []
  }
}

## Update Rules
1. After each response: update message_count
2. After each user message: re-scan world book activations
3. Every 5-10 turns: update character_state.mood
4. On key events: add flags
5. Chat-log.md tracks full conversation with per-turn state snapshots