import { useCallback, useMemo, useRef } from "react";
import Editor, { loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor";
import type { CursorPosition, OpenTab } from "../../types";
import { parentPath } from "../../utils/agentspacePath";
import { ConflictIcon, LockIcon } from "./TreeIcons";

loader.config({ monaco });

export interface EditorAreaProps {
  tabs: OpenTab[];
  activeTabId: string | null;
  onTabClick(id: string): void;
  onRequestClose(id: string): void;
  onContentChange(id: string, value: string): void;
  onSave(id: string): Promise<void>;
  onOpenConflict(id: string): void;
  onCursorChange(position: CursorPosition): void;
}

function shortestLabels(tabs: OpenTab[]): Map<string, string> {
  const result = new Map<string, string>();
  const groups = new Map<string, OpenTab[]>();
  for (const tab of tabs) {
    groups.set(tab.name, [...(groups.get(tab.name) || []), tab]);
  }
  for (const [name, group] of groups) {
    if (group.length === 1) {
      result.set(group[0].id, name);
      continue;
    }
    const parentSegments = group.map((tab) => parentPath(tab.path).split("/").filter(Boolean));
    for (let depth = 1; depth <= Math.max(...parentSegments.map((segments) => segments.length), 1); depth += 1) {
      const candidates = parentSegments.map((segments) => segments.slice(-depth).join("/"));
      if (new Set(candidates).size === candidates.length) {
        group.forEach((tab, index) => result.set(tab.id, `${name} — ${candidates[index] || "根目录"}`));
        break;
      }
    }
    group.forEach((tab) => {
      if (!result.has(tab.id)) result.set(tab.id, `${name} — ${parentPath(tab.path) || "根目录"}`);
    });
  }
  return result;
}

export default function EditorArea({
  tabs,
  activeTabId,
  onTabClick,
  onRequestClose,
  onContentChange,
  onSave,
  onOpenConflict,
  onCursorChange,
}: EditorAreaProps) {
  const activeTab = tabs.find((tab) => tab.id === activeTabId);
  const labels = useMemo(() => shortestLabels(tabs), [tabs]);
  const activeTabIdRef = useRef(activeTabId);
  const onSaveRef = useRef(onSave);
  const onCursorChangeRef = useRef(onCursorChange);
  activeTabIdRef.current = activeTabId;
  onSaveRef.current = onSave;
  onCursorChangeRef.current = onCursorChange;

  const handleEditorDidMount = useCallback((editor: monaco.editor.IStandaloneCodeEditor) => {
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
      if (activeTabIdRef.current) void onSaveRef.current(activeTabIdRef.current);
    });
    editor.onDidChangeCursorPosition((event) => {
      onCursorChangeRef.current({
        line: event.position.lineNumber,
        column: event.position.column,
      });
    });
    const position = editor.getPosition();
    if (position) {
      onCursorChangeRef.current({ line: position.lineNumber, column: position.column });
    }
  }, []);

  if (tabs.length === 0) {
    return (
      <div className="agentspace-editor-empty">
        <span>从 Agentspace 文件树打开文件以开始编辑。</span>
      </div>
    );
  }

  return (
    <div className="agentspace-editor">
      <div className="agentspace-tab-row">
        <div className="agentspace-tab-bar" role="tablist" aria-label="已打开文件">
          {tabs.map((tab) => (
            <div
              key={tab.id}
              className={[
                "agentspace-tab",
                tab.id === activeTabId ? "agentspace-tab-active" : "",
                tab.conflict ? "agentspace-tab-conflict" : "",
                tab.isLocked ? "agentspace-tab-locked" : "",
              ].filter(Boolean).join(" ")}
              role="tab"
              aria-selected={tab.id === activeTabId}
              title={tab.path}
              onClick={() => onTabClick(tab.id)}
            >
              <span className="agentspace-tab-name">{labels.get(tab.id) || tab.name}</span>
              {tab.conflict && <span className="agentspace-tab-state" title="存在外部冲突"><ConflictIcon /></span>}
              {tab.isLocked && <span className="agentspace-tab-state" title="Agent 使用中"><LockIcon /></span>}
              {tab.isDirty && !tab.conflict && <span className="agentspace-tab-dirty" title="未保存" />}
              <button
                className="agentspace-tab-close"
                aria-label={`关闭 ${tab.path}`}
                onClick={(event) => {
                  event.stopPropagation();
                  onRequestClose(tab.id);
                }}
              >
                ×
              </button>
            </div>
          ))}
        </div>
        <div className="agentspace-editor-actions">
          {activeTab?.conflict && (
            <button className="agentspace-editor-action conflict" onClick={() => onOpenConflict(activeTab.id)}>
              比较冲突
            </button>
          )}
          <button
            className="agentspace-editor-action"
            disabled={!activeTab?.isDirty || activeTab.isLocked || !!activeTab.conflict}
            title={activeTab?.isLocked ? "Agent 使用期间不可保存" : activeTab?.conflict ? "请先处理冲突" : "保存 (Ctrl+S)"}
            onClick={() => activeTab && void onSave(activeTab.id)}
          >
            保存
          </button>
        </div>
      </div>

      {activeTab && (
        <div className="agentspace-editor-body">
          <Editor
            path={activeTab.path}
            height="100%"
            language={activeTab.language}
            value={activeTab.content}
            theme="vs-dark"
            options={{
              readOnly: activeTab.isLocked,
              minimap: { enabled: true },
              lineNumbers: "on",
              fontSize: 14,
              fontFamily: "'Cascadia Code', 'SF Mono', Monaco, 'Courier New', monospace",
              scrollBeyondLastLine: false,
              wordWrap: "on",
              tabSize: 2,
              insertSpaces: true,
              automaticLayout: true,
            }}
            onChange={(value) => {
              if (value !== undefined) onContentChange(activeTab.id, value);
            }}
            onMount={handleEditorDidMount}
          />
        </div>
      )}
    </div>
  );
}
