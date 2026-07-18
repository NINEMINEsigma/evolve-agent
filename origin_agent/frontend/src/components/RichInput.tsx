import React, { useCallback, useEffect, useImperativeHandle, useRef, useState, type ClipboardEvent, type KeyboardEvent } from "react";
import type { PendingImage } from "../hooks/useWebSocket";
import MentionMenu, { type MentionItem } from "./MentionMenu";

interface RichInputProps {
  value: string;
  onChange: (html: string, text: string) => void;
  onSend: () => void;
  onPasteImage: (file: File) => Promise<{ id: string; dataUrl: string } | null>;
  onRemoveImage: (id: string) => void;
  pendingImages: PendingImage[];
  disabled?: boolean;
  placeholder?: string;
}

// ── mention 状态 ──────────────────────────────────────────────

interface MentionState {
  trigger: "" | "@" | "/";   // "" 表示未激活
  query: string;          // @ 或 / 之后的搜索文本
  range: Range | null;    // 触发字符前的选区快照
  items: MentionItem[];
  selectedIndex: number;
  position: { x: number; y: number; openUpward: boolean };
}

const MENTION_NONE: MentionState = {
  trigger: "",
  query: "",
  range: null,
  items: [],
  selectedIndex: 0,
  position: { x: 0, y: 0, openUpward: false },
};

// ── 数据加载 (带 TTL 缓存) ────────────────────────────────────

const CACHE_TTL = 30_000; // 30 秒后过期，确保 agent 运行中新增的文件/skill 能同步

// skills 缓存
let _skillsCache: { items: MentionItem[]; ts: number } | null = null;
async function loadSkillItems(): Promise<MentionItem[]> {
  if (_skillsCache && Date.now() - _skillsCache.ts < CACHE_TTL) {
    return _skillsCache.items;
  }
  try {
    const res = await fetch("/api/skills/list");
    const data = await res.json();
    const items: MentionItem[] = (data.skills || []).map((s: any) => ({
      id: s.name,
      label: s.name,
      description: s.description,
      icon: "skill" as const,
    }));
    _skillsCache = { items, ts: Date.now() };
    return items;
  } catch {
    return [];
  }
}

// agentspace 目录缓存: dir → { items, ts }
const _agentspaceDirCache = new Map<string, { items: MentionItem[]; ts: number }>();

async function loadAgentspaceItems(query: string): Promise<MentionItem[]> {
  try {
    const dir = query.includes("/") ? query.substring(0, query.lastIndexOf("/")) : "";
    const filter = query.includes("/") ? query.substring(query.lastIndexOf("/") + 1) : query;

    // 先查缓存，过期则重新加载
    let cached = _agentspaceDirCache.get(dir);
    let entries: MentionItem[];
    if (cached && Date.now() - cached.ts < CACHE_TTL) {
      entries = cached.items;
    } else {
      const res = await fetch(`/api/agentspace/list?path=${encodeURIComponent(dir)}`);
      const data = await res.json();
      const raw: any[] = data.entries || [];
      entries = raw.map((e) => {
        const fullPath = dir ? `${dir}/${e.name}` : e.name;
        return {
          id: fullPath,
          label: e.name,
          description: e.type === "dir" ? "目录" : "",
          icon: e.type === "dir" ? ("dir" as const) : ("file" as const),
        };
      });
      _agentspaceDirCache.set(dir, { items: entries, ts: Date.now() });
    }

    return filter
      ? entries.filter((e) => e.label.toLowerCase().includes(filter.toLowerCase()))
      : entries;
  } catch {
    return [];
  }
}

// ── 组件 ──────────────────────────────────────────────────────

const RichInput = React.forwardRef<HTMLDivElement, RichInputProps>(function RichInput({
  value,
  onChange,
  onSend,
  onPasteImage,
  onRemoveImage,
  pendingImages,
  disabled,
  placeholder,
}, ref) {
  const innerRef = useRef<HTMLDivElement>(null);
  useImperativeHandle(ref, () => innerRef.current!);
  const divRef = innerRef;
  const [isEmpty, setIsEmpty] = useState(!value);
  const [mention, setMention] = useState<MentionState>(MENTION_NONE);
  const mentionRef = useRef<MentionState>(MENTION_NONE);
  mentionRef.current = mention;
  const loadTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 组件挂载时预加载 agentspace 根目录和 skills 列表，让首次 @ 或 / 能立刻显示菜单
  useEffect(() => {
    loadAgentspaceItems("");
    loadSkillItems();
  }, []);

  useEffect(() => {
    const el = divRef.current;
    if (!el) return;
    const currentText = el.innerText || "";
    if (value !== el.innerHTML && value !== currentText) {
      el.innerHTML = value;
      setIsEmpty(!el.innerText?.trim() && !el.querySelector(".input-inline-image"));
      autoResize();
    }
  }, [value]);

  useEffect(() => {
    const el = divRef.current;
    if (!el) return;
    const ids = new Set(pendingImages.map((img) => img.id));
    el.querySelectorAll<HTMLSpanElement>(".input-inline-image").forEach((node) => {
      if (!ids.has(node.dataset.imageId || "")) {
        node.remove();
      }
    });
    setIsEmpty(!el.innerText?.trim() && !el.querySelector(".input-inline-image"));
  }, [pendingImages]);

  const notifyChange = () => {
    const el = divRef.current;
    if (!el) return;
    const html = el.innerHTML;
    const text = el.innerText || "";
    setIsEmpty(!text.trim() && !el.querySelector(".input-inline-image"));
    onChange(html, text);
  };

  const autoResize = () => {
    const el = divRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  };

  // ── mention 核心逻辑 ─────────────────────────────────────────

  // 检测光标前是否有未完成的 @ 或 / 触发
  const detectMention = useCallback(() => {
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount) return;
    const range = sel.getRangeAt(0);
    if (!divRef.current?.contains(range.commonAncestorContainer)) return;

    // 取光标所在文本节点中光标之前的文本
    const node = range.startContainer;
    if (node.nodeType !== Node.TEXT_NODE) {
      setMention(MENTION_NONE);
      return;
    }
    const textBefore = (node.textContent || "").substring(0, range.startOffset);

    // 查找最后一个未被空格截断的 @ 或 /
    const atIdx = textBefore.lastIndexOf("@");
    const slashIdx = textBefore.lastIndexOf("/");
    const triggerIdx = Math.max(atIdx, slashIdx);
    if (triggerIdx === -1) {
      setMention(MENTION_NONE);
      return;
    }

    const triggerChar = textBefore[triggerIdx] as "@" | "/";
    const query = textBefore.substring(triggerIdx + 1);

    // 触发字符和查询文本之间不能有空格或换行
    if (/[\s\n]/.test(query)) {
      setMention(MENTION_NONE);
      return;
    }

    // 计算菜单位置: 使用视口坐标 (position:fixed)，避免 absolute 超出视口时撑大页面
    const probeRange = document.createRange();
    probeRange.setStart(node, triggerIdx);
    probeRange.setEnd(node, triggerIdx + 1);
    const probeRect = probeRange.getBoundingClientRect();

    // 判断下方空间是否足够，不够则向上展开
    const MENU_MAX_H = 244;
    const spaceBelow = window.innerHeight - probeRect.bottom;
    const openUpward = spaceBelow < MENU_MAX_H && probeRect.top > MENU_MAX_H;
    const menuX = probeRect.left;
    const menuY = openUpward ? probeRect.top : probeRect.bottom;

    setMention({
      trigger: triggerChar,
      query,
      range: range.cloneRange(),
      items: [],
      selectedIndex: 0,
      position: { x: menuX, y: menuY, openUpward },
    });
  }, []);

  // debounce 加载菜单数据
  useEffect(() => {
    if (loadTimer.current) clearTimeout(loadTimer.current);
    if (mention === MENTION_NONE) return;

    loadTimer.current = setTimeout(async () => {
      const current = mentionRef.current;
      let items: MentionItem[];
      if (current.trigger === "/") {
        const allSkills = await loadSkillItems();
        items = current.query
          ? allSkills.filter((s) =>
              s.label.toLowerCase().includes(current.query.toLowerCase()),
            )
          : allSkills;
      } else {
        items = await loadAgentspaceItems(current.query);
      }
      setMention((prev) =>
        prev === MENTION_NONE
          ? prev
          : { ...prev, items, selectedIndex: 0 },
      );
    }, 180);

    return () => {
      if (loadTimer.current) clearTimeout(loadTimer.current);
    };
  }, [mention.trigger, mention.query]);

  // ── 插入 mention 标签 ─────────────────────────────────────────

  const insertMention = useCallback((item: MentionItem) => {
    const m = mentionRef.current;
    if (m === MENTION_NONE || !m.range) return;
    const el = divRef.current;
    if (!el) return;

    // 删除从触发字符到当前光标的内容
    const sel = window.getSelection();
    if (!sel) return;
    sel.removeAllRanges();
    sel.addRange(m.range);

    // 扩展选区到触发字符前
    const delRange = document.createRange();
    delRange.setStart(m.range.startContainer, m.range.startOffset - (m.trigger.length + m.query.length));
    delRange.setEnd(m.range.startContainer, m.range.startOffset);
    delRange.deleteContents();

    // 构建标签文本
    const tagText = m.trigger === "@"
      ? `@ws:${item.id}`
      : `/skill:${item.id}`;

    // 创建不可编辑的 chip 节点
    const chip = document.createElement("span");
    chip.className = "input-mention-chip";
    chip.contentEditable = "false";
    chip.dataset.mentionType = m.trigger === "@" ? "file" : "skill";
    chip.dataset.mentionValue = item.id;
    chip.textContent = tagText;
    // 末尾加一个空格方便继续输入
    const space = document.createTextNode("\u00A0");

    // 插入 chip + 空格
    delRange.insertNode(chip);
    delRange.setStartAfter(chip);
    delRange.collapse(true);
    delRange.insertNode(space);
    delRange.setStartAfter(space);
    delRange.collapse(true);
    sel.removeAllRanges();
    sel.addRange(delRange);

    setMention(MENTION_NONE);
    notifyChange();
    autoResize();
  }, []);

  // ── 事件处理 ─────────────────────────────────────────────────

  const handleInput = () => {
    notifyChange();
    autoResize();
    detectMention();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const m = mentionRef.current;
    const menuOpen = m !== MENTION_NONE && m.items.length > 0;

    if (menuOpen) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setMention((prev) =>
          prev === MENTION_NONE
            ? prev
            : { ...prev, selectedIndex: (prev.selectedIndex + 1) % prev.items.length },
        );
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setMention((prev) =>
          prev === MENTION_NONE
            ? prev
            : { ...prev, selectedIndex: (prev.selectedIndex - 1 + prev.items.length) % prev.items.length },
        );
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        if (m.items[m.selectedIndex]) {
          insertMention(m.items[m.selectedIndex]);
        }
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setMention(MENTION_NONE);
        return;
      }
    }

    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  // 退格删除 chip — 通过 nativeEvent 取 inputType 判断退格操作
  const handleBeforeInput = (e: React.InputEvent<HTMLDivElement>) => {
    const native = e.nativeEvent as unknown as InputEvent;
    if (native.inputType === "deleteContentBackward") {
      const sel = window.getSelection();
      if (!sel || !sel.rangeCount) return;
      const range = sel.getRangeAt(0);
      if (range.startOffset === 0) {
        const prev = range.startContainer.previousSibling as HTMLElement | null;
        if (prev?.classList?.contains("input-mention-chip")) {
          e.preventDefault();
          prev.remove();
          notifyChange();
          autoResize();
        }
      }
    }
  };

  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    const removeBtn = target.closest(".input-inline-remove") as HTMLButtonElement | null;
    if (removeBtn) {
      const wrapper = removeBtn.closest(".input-inline-image") as HTMLSpanElement | null;
      if (wrapper) {
        const id = wrapper.dataset.imageId;
        if (id) onRemoveImage(id);
        wrapper.remove();
        e.preventDefault();
        notifyChange();
        autoResize();
      }
      return;
    }
    // 点击 chip 外部关闭菜单
    if (!target.closest(".mention-menu")) {
      // onBlur 会处理
    }
  };

  const handleBlur = (e: React.FocusEvent<HTMLDivElement>) => {
    // 如果焦点转移到菜单，不关闭
    const nextFocused = e.relatedTarget as HTMLElement | null;
    if (nextFocused?.closest?.(".mention-menu")) return;
    // 延迟关闭，给 mousedown 事件时间触发
    setTimeout(() => {
      const active = document.activeElement;
      if (!active?.closest?.(".mention-menu")) {
        setMention(MENTION_NONE);
      }
    }, 150);
    notifyChange();
  };

  const insertNodeAtCursor = (node: Node) => {
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount) {
      divRef.current?.appendChild(node);
      return true;
    }
    const range = sel.getRangeAt(0);
    if (!divRef.current?.contains(range.commonAncestorContainer)) {
      divRef.current?.appendChild(node);
      return true;
    }
    range.deleteContents();
    range.insertNode(node);
    range.setStartAfter(node);
    range.setEndAfter(node);
    sel.removeAllRanges();
    sel.addRange(range);
    return true;
  };

  const handlePaste = async (e: ClipboardEvent<HTMLDivElement>) => {
    const items = e.clipboardData?.files;
    if (!items || items.length === 0) return;
    const imageFiles = Array.from(items).filter((f) => f.type.startsWith("image/"));
    if (imageFiles.length === 0) return;
    e.preventDefault();

    for (const file of imageFiles) {
      const result = await onPasteImage(file);
      if (!result) continue;
      const { id, dataUrl } = result;
      const wrapper = document.createElement("span");
      wrapper.className = "input-inline-image";
      wrapper.contentEditable = "false";
      wrapper.dataset.imageId = id;
      wrapper.innerHTML = `<img src="${dataUrl}" alt="" /><button type="button" class="input-inline-remove">×</button>`;
      wrapper.querySelector(".input-inline-remove")?.addEventListener("click", () => {
        onRemoveImage(id);
        wrapper.remove();
        notifyChange();
        autoResize();
      });
      insertNodeAtCursor(wrapper);
    }
    notifyChange();
    autoResize();
  };

  const menuOpen = mention !== MENTION_NONE && mention.items.length > 0;

  return (
    <div className="rich-input-wrapper">
      <div
        ref={divRef}
        className="rich-input"
        contentEditable={!disabled}
        onInput={handleInput}
        onKeyDown={handleKeyDown}
        onBeforeInput={handleBeforeInput}
        onPaste={handlePaste}
        onClick={handleClick}
        onBlur={handleBlur}
        data-placeholder={placeholder}
        suppressContentEditableWarning
      />
      {menuOpen && (
        <MentionMenu
          items={mention.items}
          selectedIndex={mention.selectedIndex}
          onSelect={insertMention}
          position={mention.position}
        />
      )}
      {isEmpty && placeholder && (
        <div className="rich-input-placeholder">{placeholder}</div>
      )}
    </div>
  );
});

export default RichInput;