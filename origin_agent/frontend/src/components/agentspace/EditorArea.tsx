import { useCallback } from "react";
import Editor, { loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor";
import type { OpenTab } from "../../types";

// 使用本地 monaco-editor，避免从 jsdelivr CDN 加载
loader.config({ monaco });

interface EditorAreaProps {
  tabs: OpenTab[];
  activeTabId: string | null;
  locked: boolean;
  onTabClick: (id: string) => void;
  onTabClose: (id: string) => void;
  onContentChange: (id: string, value: string) => void;
  onSave: (id: string) => void;
}

export default function EditorArea({
  tabs,
  activeTabId,
  locked,
  onTabClick,
  onTabClose,
  onContentChange,
  onSave,
}: EditorAreaProps) {
  const activeTab = tabs.find((t) => t.id === activeTabId);

  const handleEditorDidMount = useCallback(
    (_editor: any, _monaco: any) => {
      _editor.addCommand(_monaco.KeyMod.CtrlCmd | _monaco.KeyCode.KeyS, () => {
        if (activeTabId) onSave(activeTabId);
      });
    },
    [activeTabId, onSave]
  );

  if (tabs.length === 0) {
    return (
      <div className="agentspace-editor-empty">
        <span>Open a file from the explorer to start editing.</span>
      </div>
    );
  }

  return (
    <div className="agentspace-editor">
      {/* Tab Bar */}
      <div className="agentspace-tab-bar">
        {tabs.map((tab) => (
          <div
            key={tab.id}
            className={`agentspace-tab ${tab.id === activeTabId ? "agentspace-tab-active" : ""}`}
            onClick={() => onTabClick(tab.id)}
          >
            <span className="agentspace-tab-name">{tab.name}</span>
            {tab.isDirty && <span className="agentspace-tab-dirty" />}
            <button
              className="agentspace-tab-close"
              onClick={(e) => {
                e.stopPropagation();
                onTabClose(tab.id);
              }}
            >
              &times;
            </button>
          </div>
        ))}
      </div>

      {/* Editor */}
      {activeTab && (
        <div className="agentspace-editor-body">
          <Editor
            key={activeTab.id}
            height="100%"
            language={activeTab.language}
            value={activeTab.content}
            theme="vs-dark"
            options={{
              readOnly: locked,
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
              if (activeTabId && value !== undefined) onContentChange(activeTabId, value);
            }}
            onMount={handleEditorDidMount}
          />
        </div>
      )}
    </div>
  );
}