from enum import Enum
from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# LSP Types
# ---------------------------------------------------------------------------

class LSPState(str, Enum):
    """LSP server 生命周期状态。

    IDLE      : 未启动，无 pyright 进程运行。
    STARTING  : 正在启动 pyright 并等待初始化握手 + 索引就绪。
    READY     : pyright 已就绪，可以接受查询请求。
    """

    IDLE = "idle"
    STARTING = "starting"
    READY = "ready"


class LSPDiagnostic(BaseModel):
    """单条 LSP 诊断信息。"""
    model_config = ConfigDict(frozen=True)

    severity: str  # "error" | "warning" | "information" | "hint"
    line: int      # 1-indexed
    column: int    # 1-indexed (character offset)
    end_line: int
    end_column: int
    message: str
    source: str = "pyright"
    code: str | None = None


class LSPReference(BaseModel):
    """单条引用位置。"""
    model_config = ConfigDict(frozen=True)

    file: str       # 逻辑路径 (如 "fork:main.py")
    line: int       # 1-indexed
    column: int     # 1-indexed
    end_line: int
    end_column: int
    preview: str    # 匹配行文本


class LSPDefinition(BaseModel):
    """符号定义位置。"""
    model_config = ConfigDict(frozen=True)

    file: str | None  # 逻辑路径，None 表示未找到
    line: int
    column: int
    end_line: int
    end_column: int
    preview: str


class LSPSymbol(BaseModel):
    """文件内符号。"""
    model_config = ConfigDict(frozen=True)

    name: str
    kind: str       # LSP SymbolKind 名称 (如 "Function", "Class", "Variable")
    line: int
    column: int
    end_line: int
    end_column: int
    detail: str | None = None
    children: list["LSPSymbol"] = Field(default_factory=list)