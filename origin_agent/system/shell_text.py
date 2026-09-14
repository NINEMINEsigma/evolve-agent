"""ConPTY 输出到 Agent 可读文本的增量规范化。"""

from __future__ import annotations


class ShellTextNormalizer:
    """将终端重绘折叠为稳定的追加式逻辑行文本。"""

    _NORMAL = "normal"
    _ESC = "esc"
    _CSI = "csi"
    _OSC = "osc"
    _OSC_ESC = "osc_esc"
    _ST = "st"
    _ST_ESC = "st_esc"

    def __init__(self) -> None:
        self._state = self._NORMAL
        self._csi_params = ""
        self._line: list[str] = []
        self._cursor = 0
        self._pending_cr = False
        self._ignore_next_lf = False

    def feed(self, text: str) -> str:
        """消费原始终端文本块；未换行逻辑行暂不返回。"""
        output: list[str] = []
        for char in text:
            if self._pending_cr:
                self._pending_cr = False
                if char == "\n":
                    output.append(self._commit_line())
                    continue
                self._cursor = 0

            if self._ignore_next_lf:
                self._ignore_next_lf = False
                if char == "\n":
                    continue

            if self._state == self._NORMAL:
                if char == "\x1b":
                    self._state = self._ESC
                elif char == "\r":
                    self._pending_cr = True
                elif char == "\n":
                    output.append(self._commit_line())
                elif char == "\b":
                    if self._cursor > 0:
                        self._cursor -= 1
                        del self._line[self._cursor]
                elif char == "\t":
                    self._put_text("\t")
                elif ord(char) >= 32 and ord(char) != 127:
                    self._put_text(char)
                continue

            if self._state == self._ESC:
                if char == "[":
                    self._state = self._CSI
                    self._csi_params = ""
                elif char == "]":
                    self._state = self._OSC
                elif char in ("P", "X", "^", "_"):
                    self._state = self._ST
                else:
                    self._state = self._NORMAL
                continue

            if self._state == self._CSI:
                if 0x30 <= ord(char) <= 0x3F:
                    self._csi_params += char
                    continue
                if 0x20 <= ord(char) <= 0x2F:
                    continue
                if 0x40 <= ord(char) <= 0x7E:
                    self._apply_csi(char, self._csi_params)
                    self._state = self._NORMAL
                continue

            if self._state == self._OSC:
                if char == "\x07":
                    self._state = self._NORMAL
                elif char == "\x1b":
                    self._state = self._OSC_ESC
                continue

            if self._state == self._OSC_ESC:
                self._state = self._NORMAL if char == "\\" else self._OSC
                continue

            if self._state == self._ST:
                if char == "\x1b":
                    self._state = self._ST_ESC
                continue

            if self._state == self._ST_ESC:
                self._state = self._NORMAL if char == "\\" else self._ST

        return "".join(output)

    @property
    def has_pending_output(self) -> bool:
        """返回是否存在尚未提交的可见逻辑行或待处理 CR。"""
        return bool(self._line) or self._pending_cr

    def flush_pending(self) -> str:
        """在静默边界提交当前未换行逻辑行。"""
        if self._pending_cr:
            self._pending_cr = False
            self._cursor = 0
            self._ignore_next_lf = True
        if not self._line:
            return ""
        return self._commit_line()

    def finish(self) -> str:
        """在 EOF 时提交最后逻辑行并清理控制状态。"""
        result = self.flush_pending()
        self._state = self._NORMAL
        self._csi_params = ""
        return result

    def _put_text(self, text: str) -> None:
        if self._cursor > len(self._line):
            self._line.extend(" " for _ in range(self._cursor - len(self._line)))
        end = self._cursor + len(text)
        if end > len(self._line):
            self._line.extend(" " for _ in range(end - len(self._line)))
        self._line[self._cursor:end] = list(text)
        self._cursor = end

    def _commit_line(self) -> str:
        line = "".join(self._line).rstrip(" ")
        self._line.clear()
        self._cursor = 0
        return line + "\n"

    def _apply_csi(self, final: str, raw_params: str) -> None:
        params = raw_params.lstrip("?")
        values: list[int] = []
        for item in params.split(";") if params else []:
            try:
                values.append(int(item) if item else 0)
            except ValueError:
                values.append(0)
        first = values[0] if values else 0
        amount = first or 1

        if final == "K":
            if first == 0:
                del self._line[self._cursor:]
            elif first == 1:
                del self._line[: min(self._cursor, len(self._line))]
                self._cursor = 0
            elif first == 2:
                self._line.clear()
                self._cursor = 0
        elif final == "P":
            del self._line[self._cursor:self._cursor + amount]
        elif final == "@":
            self._line[self._cursor:self._cursor] = [" "] * amount
        elif final == "C":
            self._cursor = min(len(self._line), self._cursor + amount)
        elif final == "D":
            self._cursor = max(0, self._cursor - amount)
        elif final == "G":
            self._cursor = max(0, (first or 1) - 1)
        elif final == "d":
            # 单逻辑行模型不维护垂直屏幕，消费为 no-op。
            return
        elif final == "m":
            return
