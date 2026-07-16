from typing import * # type: ignore
import logging
from pydantic import BaseModel, Field, PrivateAttr
from entity.puretype import Role
from entity.constant import USER_CHARACTER_NAME, ALL_AGENTS_CHARACTER_REF_NAME
from system.templates import read_template
from threading import Lock

logger = logging.getLogger(__name__)


class MessageBlock(BaseModel):
    def as_object(self) -> dict:
        raise NotImplementedError("Subclass must implement this method")


class TextBlock(MessageBlock):
    text: str = Field(..., description="The text of the block")
    def as_object(self) -> dict[str, str]:
        return {
            "type": "text",
            "text": self.text
        }


class ImageBlock(MessageBlock):
    image_url: str = Field(..., description="The url of the image")
    def as_object(self) -> dict:
        return {
            "type": "image_url",
            "image_url": {
                "url": self.image_url
            }
        }


class VideoBlock(MessageBlock):
    video_url: str = Field(..., description="The url of the video")
    def as_object(self) -> dict:
        return {
            "type": "video_url",
            "video_url": {
                "url": self.video_url
            }
        }


class AudioBlock(MessageBlock):
    audio_url: str = Field(..., description="The url of the audio")
    def as_object(self) -> dict:
        return {
            "type": "audio_url",
            "audio_url": {
                "url": self.audio_url
            }
        }


class BaseMessage(BaseModel):
    content: str|list[MessageBlock] = Field(description="The content of the message")
    role: Role = Field(description="The role of the message")

    def as_content(self, 
        # 当前作为运行中的agent的角色
        current_character_agent:str, 
        **kwargs
        ) -> str|list|None:
        '''
        将message转换为字符串或列表, 并合成必要的前缀后缀以及格式化

        Args:
            current_character_agent: 当前作为运行中的agent的角色
            kwargs: 格式化参数

        Returns:
            str|list: 转换后的字符串或列表
        '''
        content: str|list[MessageBlock]|list[Any] = self.content
        if isinstance(content, str):
            result = str(content)
            for key, value in kwargs.items():
                result = result.replace("{{" + key + "}}", str(value))
        else:
            e = len(content)
            result = [None] * e
            for i in range(e):
                cur = content[i]
                if isinstance(cur, TextBlock):
                    temp = cur.as_object()
                    for key, value in kwargs.items():
                        temp["text"] = temp["text"].replace("{{" + key + "}}", str(value))
                    result[i] = temp # type: ignore
                else:
                    result[i] = cur.as_object() # type: ignore
        return result

    def is_visible_to(self, current_character_agent: str) -> bool:
        """纯可见性判断，无副作用。"""
        return True


class CharacterMessage(BaseMessage):
    character_name: str = Field(..., description="The character name of the message")

    def is_visible_to(self, current_character_agent: str) -> bool:
        # 角色作用域消息默认仅对自身可见
        return self.character_name == current_character_agent


class CharacterSystemMessage(CharacterMessage):
    def as_content(self,
        # 当前作为运行中的agent的角色
        current_character_agent:str, 
        **kwargs
        ) -> str|list[MessageBlock]|None:
        '''
        如果不是当前角色的提示词, 被略过, 返回None
        '''
        if current_character_agent != self.character_name:
            return None
        return super().as_content(current_character_agent, **kwargs)


_Role_Prefix_Template: str|None = None
_Identity_Prefix_Template: str|None = None


class FunctionCall(BaseModel):
    name: str = Field(..., description="The name of the function call")
    arguments: str = Field(..., description="The arguments of the function call")

    def as_object(self) -> dict:
        return {
            "name": self.name,
            "arguments": self.arguments
        }


class ToolCall(BaseModel):
    id: str = Field(..., description="The id of the tool call")
    type: str = Field("function", description="The type of the tool call")
    function: FunctionCall = Field(..., description="The function of the tool call")

    def as_object(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "function": self.function.as_object()
        }


class CharacterConversationMessage(CharacterMessage):
    # ----------------------------------------
    # v1字段区域
    # ----------------------------------------
    '''
    角色对话消息, 始终被消息的发起者和用户可见, 其余agent可见性由字段控制
    '''
    reasoning: str|None = None
    '''
    思考内容
    '''
    # 字段名应由 LLM 响应实际使用的 provider 字段决定；默认仅作为无响应信息时的兜底。
    reasoning_field_name: str|None = "reasoning_content"
    '''
    思考内容字段名
    '''
    visible_characters: list[str]|None = None
    '''
    可见角色列表, 为空时仅用户和自己可见
    '''
    response_characters: list[str]|None = None
    '''
    需要响应的角色列表, 为空时表示所有角色都需要响应
    '''
    tool_calls: list[ToolCall]|None = None
    '''
    工具调用列表
    '''
    message_suffix: str|None = None
    '''
    消息后缀
    '''
    dynamic_message_suffix: str|None = None
    '''
    动态消息后缀
    '''

    def with_suffix(
        self, 
        message_suffix: str | None) -> "CharacterConversationMessage":
        """返回带新 message_suffix, dynamic_positive_suffix, dynamic_negative_suffix 的副本（不影响原对象）。"""
        return self.model_copy(update={
            "message_suffix": message_suffix, 
            })

    def is_visible_to(self, current_character_agent: str) -> bool:
        # 自己始终可见
        if self.character_name == current_character_agent:
            return True
        # visible_characters 为空/None 时仅自己可见 — 非自身角色不可见
        if not self.visible_characters:
            return False
        # 显式列表检查（含 all-agents 通配）
        return (current_character_agent in self.visible_characters or
                ALL_AGENTS_CHARACTER_REF_NAME in self.visible_characters)

    def as_content(
        self,
        # 当前作为运行中的agent的角色
        current_character_agent:str, 
        is_last_user_message: bool = False,
        **kwargs
        ) -> str|list[MessageBlock]|None:
        '''
        获取角色对话消息的字符串内容, 如果不可见将被略过, 可见时将会对所有非消息接收者第一人称的消息都施加前缀修饰
        '''
        # 可见性前置检查 — 避免不可见消息的格式化开销
        if not self.is_visible_to(current_character_agent):
            return None

        is_self_current = self.character_name == current_character_agent

        # 非持久化注入的suffix
        non_persistent_injection_suffix = ""
        if is_last_user_message:
            non_persistent_injection_suffix = self.dynamic_message_suffix

        global _Role_Prefix_Template
        raw_message = super().as_content(current_character_agent, **kwargs)
        # 如果当前是消息接收者第一人称的消息, 则直接返回原始消息
        if is_self_current:
            return raw_message
        # 如果前缀模板未加载, 则加载
        if _Role_Prefix_Template is None:
            _Role_Prefix_Template = read_template("messages/role_prefix.txt")
        # 加载身份前缀模板（仅在最后一条消息前使用）
        if is_last_user_message:
            global _Identity_Prefix_Template
            if _Identity_Prefix_Template is None:
                _Identity_Prefix_Template = read_template("messages/identity_prefix.txt")
        # 替换前缀模板中的占位符
        prefix = _Role_Prefix_Template
        response_characters = self.response_characters
        if response_characters:
            response_str = ", ".join(response_characters)
        else:
            response_str = "the current agent"
        prefix = prefix.replace("{{RESPONSE_CHARACTERS}}", response_str)
        prefix = prefix.replace("{{MESSAGE_SENDER}}", self.character_name)
        if self.visible_characters:
            prefix = prefix.replace("{{VISIBLE_CHARACTERS}}", f"{', '.join(self.visible_characters)} and the {USER_CHARACTER_NAME}")
        else:
            prefix = prefix.replace("{{VISIBLE_CHARACTERS}}", f"Just {USER_CHARACTER_NAME}")
        # 如果是最后一条用户消息，在最前面加入身份声明
        if is_last_user_message:
            identity_line = _Identity_Prefix_Template.replace("{{CURRENT_CHARACTER}}", current_character_agent)
            prefix = identity_line + prefix
        # 返回修饰后的消息
        return f"{prefix}\n---\n{raw_message}\n---\n{self.message_suffix}{non_persistent_injection_suffix}"


class ToolResultMessage(CharacterMessage):
    '''
    工具调用结果
    '''
    tool_call_id: str = Field(description="The id of the tool call")

    @classmethod
    def from_result(
        cls,
        tool_call_id: str,
        character_name: str,
        result: Any,
    ) -> "ToolResultMessage":
        """从工具返回结果构造 ToolResultMessage，自动识别 _image 并生成 content blocks。"""
        from entry.agent_support.multimodal import tool_result_to_content
        return cls(
            role=Role.TOOL,
            character_name=character_name,
            tool_call_id=tool_call_id,
            content=tool_result_to_content(result),
        )



class History(BaseModel):
    messages: list[BaseMessage] = Field(default_factory=list, description="The messages of the history")
    last_user_message: CharacterConversationMessage|None = Field(default=None, description="The last user message of the history")
    _io_locker: Lock = PrivateAttr(default_factory=Lock)

    def get_messages(self, *, current_character_agent: str) -> list[BaseMessage]:
        """返回过滤后对当前 agent 可见的原始 BaseMessage 对象列表。

        由 ``BaseLLMClient.chat()`` 接收，客户端在发送前自行转换格式。
        """
        result: list[BaseMessage] = []
        for message in self.messages:
            if not message.is_visible_to(current_character_agent):
                continue
            result.append(message)
        return result

    def update_last_user_message(self) -> None:
        """重新计算并更新 last_user_message 缓存。"""
        for message in reversed(self.messages):
            if isinstance(message, CharacterConversationMessage):
                if message.role == Role.USER:
                    self.last_user_message = message
                    return
        self.last_user_message = None

    def add_message(self, message: BaseMessage) -> int:
        with self._io_locker:
            # ToolResultMessage 必须与对应 assistant 的 tool_calls 配对。
            # 由于多个 tool result 会顺序追加，不能只看 messages[-1]，
            # 需要从后向前找到最近一条包含该 tool_call_id 的 assistant 消息。
            if isinstance(message, ToolResultMessage):
                if not self.messages:
                    logger.warning(
                        "ToolResultMessage id=%s added to empty history, skipping",
                        message.tool_call_id,
                    )
                    return -1
                matched = False
                for last in reversed(self.messages):
                    if isinstance(last, CharacterConversationMessage) and last.tool_calls:
                        if any(tc.id == message.tool_call_id for tc in last.tool_calls):
                            matched = True
                            break
                if not matched:
                    logger.warning(
                        "ToolResultMessage id=%s does not match any assistant tool_calls, skipping",
                        message.tool_call_id,
                    )
                    return -1
            if isinstance(message, CharacterConversationMessage):
                # 上下文编排, 通过RAG等手段获取关于这条消息的正面与负面相关记忆
                # 形成类似奖惩机制的关联性长期记忆
                pass
            self.messages.append(message)
            self.update_last_user_message()
            return len(self.messages) - 1

    def insert_message(self, message: BaseMessage, index: int) -> bool:
        with self._io_locker:
            if index < 0 or index > len(self.messages):
                return False
            self.messages.insert(index, message)
            self.update_last_user_message()
            return True

    def remove_message(self, index: int) -> bool:
        with self._io_locker:
            if index < 0 or index >= len(self.messages):
                return False
            self.messages.pop(index)
            self.update_last_user_message()
            return True
        return False

    def remove_unpaired_tool_calls(self) -> None:
        """移除所有没有对应 ToolResultMessage 的 tool_calls。"""
        with self._io_locker:
            result_ids: set[str] = {
                msg.tool_call_id
                for msg in self.messages
                if isinstance(msg, ToolResultMessage)
            }
            for msg in self.messages:
                if isinstance(msg, CharacterConversationMessage) and msg.tool_calls:
                    msg.tool_calls = [
                        tc for tc in msg.tool_calls
                        if tc.id in result_ids
                    ]

    def at_message(self, message: BaseMessage) -> int:
        with self._io_locker:
            return self.messages.index(message)

    def get_message(self, index: int) -> BaseMessage:
        with self._io_locker:
            return self.messages[index]

    @property
    def count(self) -> int:
        with self._io_locker:
            return len(self.messages)

    # ---- 新增封装方法 ----

    def iter_messages(self) -> Iterator[BaseMessage]:
        """只读迭代消息列表（返回快照副本的迭代器）。"""
        with self._io_locker:
            return iter(list(self.messages))

    def set_message(self, index: int, message: BaseMessage) -> None:
        """替换指定索引的消息。"""
        with self._io_locker:
            if index < 0 or index >= len(self.messages):
                return
            self.messages[index] = message
            self.update_last_user_message()

    def truncate_to(self, index: int) -> None:
        """截断消息列表到指定索引（保留 messages[:index]）。"""
        with self._io_locker:
            self.messages = self.messages[:index]
            self.update_last_user_message()

    def clear_messages(self) -> None:
        """清空全部消息。"""
        with self._io_locker:
            self.messages.clear()
            self.update_last_user_message()

    def remove_last_message(self) -> BaseMessage | None:
        """弹出并返回最后一条消息；列表为空时返回 None。"""
        with self._io_locker:
            if not self.messages:
                return None
            msg = self.messages.pop()
            self.update_last_user_message()
            return msg

    def find_last_user_message_index(self, count: int = 1) -> int | None:
        """返回从后往前第 count 条 Role.USER 消息的索引。

        count=1 返回最后一条 user 消息的索引，不存在时返回 None。
        """
        with self._io_locker:
            user_indices = [i for i, m in enumerate(self.messages) if m.role == Role.USER]
            if not user_indices or count < 1 or count > len(user_indices):
                return None
            return user_indices[-count]

    def find_last_message(
        self,
        predicate: Callable[[BaseMessage], bool],
    ) -> tuple[int, BaseMessage] | tuple[int, None]:
        """从后向前查找第一条满足 predicate 的消息，返回 (index, message)。

        未找到时返回 (-1, None)。
        """
        with self._io_locker:
            for i in range(len(self.messages) - 1, -1, -1):
                msg = self.messages[i]
                if predicate(msg):
                    return (i, msg)
            return (-1, None)