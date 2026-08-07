"""
客户端信息固着器 hook。

在每轮用户消息中，读取 SessionManager 中的 ClientInfo，
与 cache 文件中存储的上一次值比对：
- 相同 → 返回空串（不注入），该条消息不带 client_info suffix
- 不同或首次 → 更新 cache 文件，返回格式化文本，该条消息带 client_info suffix
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def hook_tag_name(**kwargs) -> str:
    return "client_info"


def hook_fixator(session_id: str = "", workspace: str = "", **kwargs) -> str:
    # 从 SessionManager 读取当前客户端信息
    try:
        from system.application import Application
        from entity.puretype import ClientInfo
        sm = Application.current().session_manager
        current: ClientInfo | None = sm.get_client_info(session_id)
    except Exception:
        return ""
    if current is None:
        return ""

    # cache 文件路径（与 time_hook 模式一致）
    cache_path: Path = Path(workspace) / "session_cache" / session_id / "client_info.json"

    # 序列化当前值用于比对
    current_dict = current.model_dump()
    current_json = json.dumps(current_dict, ensure_ascii=False, sort_keys=True)

    # 读取上一次的 cache
    if cache_path.exists():
        try:
            cached_json = cache_path.read_text(encoding="utf-8")
            if cached_json == current_json:
                return ""  # 无变化，不注入
        except Exception:
            pass  # cache 损坏，视为首次

    # 更新 cache 文件
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(current_json, encoding="utf-8")
    except Exception:
        logger.warning("Failed to write client_info cache | session=%s", session_id)

    # 返回格式化文本
    lines = [
        f"Client Info:",
        f"- Device: {current.device_type}",
        f"- Browser: {current.browser}",
        f"- IP: {current.client_ip}",
        f"- Frontend: {current.frontend_version}",
        f"- Orientation: {current.screen_orientation}",
    ]
    return "\n".join(lines)