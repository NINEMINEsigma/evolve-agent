import { useCallback, useEffect, useState } from "react";
import { Routes, Route } from "react-router-dom";
import { AnimatePresence } from "framer-motion";
import { useWebSocket } from "./hooks/useWebSocket";
import { useGlobalTooltip } from "./hooks/useGlobalTooltip";
import Layout from "./components/Layout";
import ChatContextMenu from "./components/ChatContextMenu";
import TagEditor from "./components/TagEditor";
import SplashScreen from "./components/SplashScreen";
import { ConnectionDiagnosticsProvider } from "./context/ConnectionDiagnosticsContext";
import ErrorBoundary from "./components/ErrorBoundary";
import Agentspace from "./pages/Agentspace";
import { SessionInfo } from "./types";

function ChatApp() {
  useGlobalTooltip();
  const ws = useWebSocket();
  const [showSplash, setShowSplash] = useState(true);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; sid: string } | null>(null);
  const [tagEditorSession, setTagEditorSession] = useState<SessionInfo | null>(null);

  const handleContextMenu = useCallback((e: React.MouseEvent, sid: string) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({ x: e.clientX, y: e.clientY, sid });
  }, []);

  useEffect(() => {
    ws.fetchAllTags();
  }, []);

  return (
    <ErrorBoundary>
      {/* 正常内容始终渲染，开屏/骨架屏作为覆盖层 */}
      <div className="app">
        <ConnectionDiagnosticsProvider
          value={{
            waiting: ws.waiting,
            pendingConfirm: ws.pendingConfirm,
            streamingMessage: ws.streamingMessage,
            ignoreStaleRef: ws.ignoreStaleRef,
            lastRecvAtRef: ws.lastRecvAtRef,
            lastPongAtRef: ws.lastPongAtRef,
            recvTick: ws.recvTick,
          }}
        >
          <Layout ws={ws} onContextMenu={handleContextMenu} />
        </ConnectionDiagnosticsProvider>
        <ChatContextMenu
          contextMenu={contextMenu}
          onClose={() => setContextMenu(null)}
          sessions={ws.sessions}
          generatingTitleSessions={ws.generatingTitleSessions}
          generatingTagSessions={ws.generatingTagSessions}
          terminatingSessions={ws.terminatingSessions}
          onAutoTitle={ws.autoTitleSession}
          onAutoTag={ws.autoTagSession}
          onTogglePin={ws.togglePinSession}
          onEditTags={(sid) => setTagEditorSession(ws.sessions.find((s) => s.id === sid) || null)}
          onBranch={ws.branchSession}
          onTerminate={ws.terminateSession}
          onDelete={ws.deleteSession}
          onRegenerateSummary={ws.regenerateSummary}
        />
        {tagEditorSession && (
          <TagEditor
            session={tagEditorSession}
            allTags={ws.allTags}
            onClose={() => setTagEditorSession(null)}
            onSave={async (sid, tags) => {
              await ws.updateSessionTags(sid, tags);
              ws.fetchAllTags();
            }}
          />
        )}
      </div>

      {/* 开屏动画覆盖层 */}
      <AnimatePresence mode="wait">
        {showSplash && (
          <SplashScreen key="splash" onFinish={() => setShowSplash(false)} />
        )}
      </AnimatePresence>
    </ErrorBoundary>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<ChatApp />} />
      <Route path="/agentspace/*" element={<Agentspace />} />
    </Routes>
  );
}