import React, { createContext, useContext, useEffect, useState } from "react";

export interface ConnectionDiagnostics {
  waiting?: boolean;
  pendingConfirm?: { request_id: string } | null;
  streamingMessage?: { id: string } | null;
  ignoreStaleRef?: React.RefObject<boolean>;
  lastRecvAtRef?: React.RefObject<number>;
  lastPongAtRef?: React.RefObject<number>;
  recvTick?: number;
}

const ConnectionDiagnosticsContext = createContext<ConnectionDiagnostics>({});

export function ConnectionDiagnosticsProvider({
  value,
  children,
}: {
  value: ConnectionDiagnostics;
  children: React.ReactNode;
}) {
  return (
    <ConnectionDiagnosticsContext.Provider value={value}>
      {children}
    </ConnectionDiagnosticsContext.Provider>
  );
}

export function useConnectionDiagnostics(): ConnectionDiagnostics & { now: number } {
  const ctx = useContext(ConnectionDiagnosticsContext);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, []);

  return { ...ctx, now };
}