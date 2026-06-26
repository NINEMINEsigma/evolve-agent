import json
from datetime import datetime
import os
import sys
from pathlib import Path


def hook_tag_name(**kwargs) -> str:
    return "session_track"


def hook_message(session_id: str = "", workspace: str = "", **kwargs) -> str:
    cache_path = Path(workspace) / "session_cache" / "session_track_hook.json"
    if not cache_path.exists():
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"session_queue": [session_id]}, f, ensure_ascii=False)
        return ""
    else:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
        session_queue: list[str] = cache_data["session_queue"]
        if session_id not in session_queue:
            session_queue.append(session_id)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"session_queue": session_queue}, f, ensure_ascii=False)
            return ""
        else:
            between_sessions = session_queue[session_queue.index(session_id)+1:]
            result = f"Between this message and the user's previous message, the user was also chatting in the following conversations: {', '.join(between_sessions)}"
            session_queue.remove(session_id)
            session_queue.append(session_id)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"session_queue": session_queue}, f, ensure_ascii=False)
            if len(between_sessions) == 0:
                return ""
            else:
                return result
