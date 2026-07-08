interface StatusBarProps {
  activeFilePath: string | null;
  language: string | null;
  locked: boolean;
}

export default function StatusBar({ activeFilePath, language, locked }: StatusBarProps) {
  return (
    <div className="agentspace-status-bar">
      <div className="agentspace-status-left">
        {activeFilePath && (
          <span className="agentspace-status-item">{activeFilePath}</span>
        )}
        {language && (
          <span className="agentspace-status-item">{language}</span>
        )}
      </div>
      <div className="agentspace-status-right">
        {locked && (
          <span className="agentspace-status-item agentspace-status-locked">
            Agent is working...
          </span>
        )}
      </div>
    </div>
  );
}