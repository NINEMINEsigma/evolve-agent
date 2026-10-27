import ChatArea from "../../components/ChatArea";
import CronCountdown from "../../components/CronCountdown";
import SubagentCountdown from "../../components/SubagentCountdown";
import InputBar from "../../components/InputBar";
import type { TabRenderContext } from "./registry";

/**
 * Chat tab content layer. Wraps the existing ChatArea component tree as-is;
 * ChatArea, countdown strips and InputBar live inside the chat tab and
 * hide together with it (mounted, never unmounted by tab switches).
 */
export default function ChatTab({ ctx }: { ctx: TabRenderContext }) {
  const { ws } = ctx;

  return (
    <div className="chat-tab">
      <ChatArea
        archived={ctx.currentSessionArchived}
        onImageClick={ctx.setLightboxSrc}
        onEditMessage={ws.editMessage}
        onDeleteMessages={ws.deleteMessages}
        onDeleteSingleMessage={ws.deleteSingleMessage}
        onRegenerateResponse={ws.regenerateResponse}
        onDropFiles={ws.handleFileUpload}
        agents={ws.agents}
        onToggleMessageVisibility={ctx.onToggleMessageVisibility}
        stageState={ctx.stageState}
        chatStyleCssText={ctx.chatStyleCssText}
        chatStyleStatus={ctx.chatStyleStatus}
        chatStyleReloadKey={ctx.chatStyleReloadKey}
      >
        <CronCountdown cronTasks={ws.cronTasks} />

        <SubagentCountdown
          subagentSessions={ws.subagentSessions}
          idleCountdown={ws.subagentIdleCountdown}
        />

        <InputBar
          forceExpanded={ctx.inputTourPinned}
          uploading={ws.uploading}
          archived={ctx.currentSessionArchived}
          hasActiveProfile={!!ws.llmProfiles?.activeProfile || (ctx.targetSessions.length > 0 && !ctx.targetSessions.includes("main"))}
          sessionId={ws.sessionId}
          taskProgress={ws.taskProgress}
          onSend={() => {
            ws.send(ctx.targetSessions, ctx.visibleCharacters, ctx.responseCharacters);
          }}
          onUpload={ws.handleFileInputChange}
          onUploadClick={ws.handleUploadClick}
          onInterrupt={ws.interrupt}
          interruptStatus={ws.interruptStatus}
          onDisgust={ws.disgust}
          onResume={ws.resume}
          fileInputRef={ws.fileInputRef}
          pendingImages={ws.pendingImages}
          onRemovePendingImage={ws.removePendingImage}
          onPasteImage={ws.handlePasteImages}
          pendingAudios={ws.pendingAudios}
          onRemovePendingAudio={ws.removePendingAudio}
          onPasteAudio={ws.handlePasteAudios}
          pendingVideos={ws.pendingVideos}
          onRemovePendingVideo={ws.removePendingVideo}
          onPasteVideo={ws.handlePasteVideos}
          inputRef={ws.inputRef}
          subagentSessions={ws.subagentSessions}
          targetSessions={ctx.targetSessions}
          setTargetSessions={ctx.setTargetSessions}
          agents={ws.agents}
          visibleCharacters={ctx.visibleCharacters}
          responseCharacters={ctx.responseCharacters}
          onToggleAgentState={ctx.onToggleAgentState}
          pendingAsks={ws.pendingAsks}
          pendingConfirms={ws.pendingConfirms}
          onRespondAsk={ws.respondAsk}
          onRespondConfirm={ws.respondConfirm}
          approvalMode={ws.approvalMode}
          approvalModeSyncStatus={ws.approvalModeSyncStatus}
          approvalModelAvailable={ws.approvalModelAvailable}
          approvalModelName={ws.approvalModelName}
          onSetApprovalMode={ws.setApprovalMode}
        />
      </ChatArea>
    </div>
  );
}
