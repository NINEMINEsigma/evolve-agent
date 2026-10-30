class MetaFormatError(ValueError):
    """元数据文本不符合 [key] 分段格式。"""

    def __init__(
        self,
        line_number: int,
        reason: str
        ) -> None:
        self.line_number = line_number
        self.reason = reason
        super().__init__(f"line {line_number}: {reason}")


class LocalFontAccessError(ValueError):
    """已识别的字体读取拒绝；携带稳定 code 与 HTTP status，不含物理路径。"""

    def __init__(
        self,
        code: str,
        message: str,
        status: int
        ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
