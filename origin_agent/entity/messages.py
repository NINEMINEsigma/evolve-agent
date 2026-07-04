from typing import * # type: ignore
import logging
from pydantic import BaseModel, Field, PrivateAttr
from entity.puretype import Role
from entity.constant import USER_CHARACTER_NAME
from system.templates import get_templates_dir
from easysave import save, load
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
    content: str|list[MessageBlock] = Field(..., description="The content of the message")
    role: Role = Field(..., description="The role of the message")

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

    def as_message(self, 
        # 当前作为运行中的agent的角色
        current_character_agent:str, 
        **kwargs
        ) -> dict|None:
        '''
        将message转换为openai协议的消息格式, 并合成必要的前缀后缀以及格式化

        Args:
            current_character_agent: 当前作为运行中的agent的角色
            kwargs: 格式化参数

        Returns:
            dict: 转换后的openai协议的消息格式
        '''
        content = self.as_content(current_character_agent, **kwargs)
        if content is None:
            return None
        return {
            "role": self.role.value,
            "content": content
        }


class CharacterMessage(BaseMessage):
    character_name: str = Field(..., description="The character name of the message")


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
    reasoning: str|None = Field(None, description="The reasoning of the message")
    # TODO: 可能需要运行时自动探查
    reasoning_field_name: str = Field("reasoning_content", description="The field name of the reasoning")
    visible_characters: list[str]|None = Field(None, description="The visible characters of the message")
    # "tool_calls": [{"id": "list_uploads:0", "type": "function", "function": {"name": "list_uploads", "arguments": "{\"n\": 10}"}}]
    tool_calls: list[ToolCall]|None = Field(None, description="The tool calls of the message")
    message_suffix: str|None = Field(None, description="The suffix of the message, like hook messages")

    @classmethod
    def from_text(
        cls,
        role: Role,
        character_name: str,
        text: str,
        *,
        visible_characters: list[str] | None = None,
        reasoning: str | None = None,
        message_suffix: str | None = None,
    ) -> "CharacterConversationMessage":
        """从纯文本构造对话消息。"""
        return cls(
            role=role,
            character_name=character_name,
            content=text,
            visible_characters=visible_characters,
            reasoning=reasoning,
            message_suffix=message_suffix,
            reasoning_field_name="reasoning_content",
            tool_calls=None,
        )

    @classmethod
    def from_tool_calls(
        cls,
        role: Role,
        character_name: str,
        content: str,
        tool_calls: list[ToolCall],
        *,
        visible_characters: list[str] | None = None,
        reasoning: str | None = None,
        message_suffix: str | None = None,
    ) -> "CharacterConversationMessage":
        """从 tool_calls 构造 assistant 消息。"""
        return cls(
            role=role,
            character_name=character_name,
            content=content,
            tool_calls=tool_calls,
            visible_characters=visible_characters,
            reasoning=reasoning,
            message_suffix=message_suffix,
            reasoning_field_name="reasoning_content",
        )

    def with_suffix(self, message_suffix: str | None) -> "CharacterConversationMessage":
        """返回带新 message_suffix 的副本（不影响原对象）。"""
        return self.model_copy(update={"message_suffix": message_suffix})

    def as_content(
        self,
        # 当前作为运行中的agent的角色
        current_character_agent:str, 
        **kwargs
        ) -> str|list[MessageBlock]|None:
        '''
        获取角色对话消息的字符串内容, 如果不可见将被略过, 可见时将会对所有非消息接收者第一人称的消息都施加前缀修饰
        '''
        # 非持久化注入的suffix
        non_persistent_injection_suffix = kwargs.get("non_persistent_injection_suffix", "")
        if non_persistent_injection_suffix:
            del kwargs["non_persistent_injection_suffix"]

        global _Role_Prefix_Template
        raw_message = super().as_content(current_character_agent, **kwargs)
        # 如果当前角色不在可见角色列表中, 则略过
        if self.visible_characters and current_character_agent not in self.visible_characters:
            return None
        # 如果当前是消息接收者第一人称的消息, 则直接返回原始消息
        if current_character_agent == self.character_name:
            return raw_message
        # 如果前缀模板未加载, 则加载
        if _Role_Prefix_Template is None:
            template_path = get_templates_dir() / "messages" / "role_prefix.txt"
            with open(template_path, "r", encoding="utf-8") as f:
                _Role_Prefix_Template = f.read()
        # 替换前缀模板中的占位符
        prefix = _Role_Prefix_Template.replace("{{MESSAGE_SENDER}}", self.character_name)
        if self.visible_characters:
            prefix = prefix.replace("{{VISIBLE_CHARACTERS}}", f"{', '.join(self.visible_characters)} and the {USER_CHARACTER_NAME}")
        else:
            prefix = prefix.replace("{{VISIBLE_CHARACTERS}}", f"Just {USER_CHARACTER_NAME}")
        # 返回前缀修饰后的消息
        return f"{prefix}\n---\n{raw_message}\n---\n{self.message_suffix}{non_persistent_injection_suffix}"

    def as_message(self,
        # 当前作为运行中的agent的角色
        current_character_agent:str, 
        **kwargs
        ) -> dict|None:
        '''
        将message转换为openai协议的消息格式, 并合成必要的前缀后缀以及格式化
        '''
        raw_message = super().as_message(current_character_agent, **kwargs)
        if raw_message is None:
            return None
        if current_character_agent != self.character_name:
            # 以特殊用户消息的形式提供给目标agent
            raw_message["role"] = Role.USER.value
            return raw_message
        if self.character_name == current_character_agent and self.reasoning:
            raw_message[self.reasoning_field_name] = self.reasoning
        if self.character_name == current_character_agent and self.tool_calls:
            raw_message["tool_calls"] = [tool_call.as_object() for tool_call in self.tool_calls]
        return raw_message


class ToolResultMessage(CharacterMessage):
    '''
    工具调用结果
    '''
    tool_call_id: str = Field(..., description="The id of the tool call")

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

    def as_message(self, current_character_agent: str, **kwargs) -> dict | None:
        if current_character_agent != self.character_name:
            return None
        raw_message = super().as_message(current_character_agent, **kwargs)
        if raw_message is None:
            return None
        raw_message["tool_call_id"] = self.tool_call_id
        return raw_message


class History(BaseModel):
    # TODO: 需要解决以下问题
    # 场景 1：部分失败与重试
    # agent A 发起 tool_call，但执行过程中网络中断，tool_result 未能及时生成。
    # 当 A 重新加载 History 后，它的上下文中会包含未配对的 tool_calls（有 tool_call 但没有 tool_result）。
    # OpenAI 协议要求 tool role 消息必须紧跟在对应的 assistant tool_call 之后。这种断层可能导致 LLM 报错或行为异常。
    # 场景 2：可见性动态变化
    # 假设某条 CharacterConversationMessage 初始 visible_characters=["agent-A"]，后续你希望让 agent-B 也能看到。
    # 当前设计把可见性作为消息不可变属性，修改它需要重建消息对象。你是否接受这种“不可变消息”的语义？
    # 场景 3：用户编辑历史消息
    # 前端允许用户编辑自己的消息。如果用户编辑了一条已经被多个 agent 消费过的消息，是否需要通知所有相关 agent 重新生成？
    # 当前 History.get_messages() 是幂等的，但编辑会改变源数据，可能让某些 agent 的上下文与前端展示不一致。
    # 场景 4：并发子 agent 同时发言
    # agent-A 和 agent-B 同时生成回复，都产生了新的 CharacterConversationMessage。
    # 如果它们都写入同一个 History，消息顺序如何确定？是否需要由父 orchestrator 统一排序后再追加？
    # 场景 5：工具调用者被移除
    # agent-A 调用了工具并等待结果，但在结果返回前 agent-A 被终止或从会话中移除。
    # ToolResultMessage.character_name 指向一个不存在的 agent，这条 tool_result 将无处可去，成为孤儿消息。
    messages: list[BaseMessage] = Field(..., description="The messages of the history")
    _io_locker: Lock = PrivateAttr(default_factory=Lock)

    def get_messages(self, current_character_agent: str, **kwargs) -> list[dict]:
        result = [message.as_message(current_character_agent, **kwargs)
            for message in self.messages
            ]
        return [i for i in result if i is not None]

    def to_openai(self, current_character_agent: str, **kwargs) -> list[dict]:
        """get_messages 的别名，语义上明确表示转换为 OpenAI 格式。"""
        return self.get_messages(current_character_agent, **kwargs)

    def add_message(self, message: BaseMessage) -> int:
        with self._io_locker:
            # ToolResultMessage 必须与上一条 assistant 的 tool_calls 配对
            if isinstance(message, ToolResultMessage):
                if not self.messages:
                    logger.warning(
                        "ToolResultMessage id=%s added to empty history, skipping",
                        message.tool_call_id,
                    )
                    return -1
                last = self.messages[-1]
                if isinstance(last, CharacterConversationMessage) and last.tool_calls:
                    if not any(tc.id == message.tool_call_id for tc in last.tool_calls):
                        logger.warning(
                            "ToolResultMessage id=%s does not match last assistant tool_calls, skipping",
                            message.tool_call_id,
                        )
                        return -1
                else:
                    logger.warning(
                        "ToolResultMessage id=%s added after non-tool-calling message, skipping",
                        message.tool_call_id,
                    )
                    return -1
            self.messages.append(message)
            return len(self.messages) - 1

    def insert_message(self, message: BaseMessage, index: int) -> bool:
        with self._io_locker:
            if index < 0 or index > len(self.messages):
                return False
            self.messages.insert(index, message)
            return True
        return False

    def remove_message(self, index: int) -> bool:
        with self._io_locker:
            if index < 0 or index >= len(self.messages):
                return False
            self.messages.pop(index)
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