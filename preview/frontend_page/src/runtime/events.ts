import type { WSMessage, AgentspaceEvent } from "@origin/types";
import type { PreviewSocketSink } from "../types";

type EventListener = (name: string, value: unknown) => void;
export class PreviewEvents {
  private sockets = new Set<PreviewSocketSink>();
  private subscribers = new Map<string, Set<EventListener>>();
  private timers = new Set<ReturnType<typeof setTimeout>>();
  private tasks = new Map<string, AbortController>();
  private queues = new Map<string, Promise<void>>();
  private generations = new Map<string, number>();
  private disposed = false;
  addSocket(socket: PreviewSocketSink): () => void {
    this.sockets.add(socket);
    return () => { this.sockets.delete(socket); };
  }
  emitSession(sessionId: string, value: WSMessage): void {
    if (this.disposed) return;
    for (const socket of [...this.sockets]) if (socket.sessionId === sessionId) socket.emit(value);
  }
  broadcast(value: WSMessage): void {
    if (!this.disposed) for (const socket of [...this.sockets]) socket.emit(value);
  }
  closeSession(sessionId: string, code: number): void {
    this.cancelSession(sessionId, true);
    for (const socket of [...this.sockets]) if (socket.sessionId === sessionId) socket.terminate(code);
  }
  subscribe(channel: string, listener: EventListener): () => void {
    const listeners = this.subscribers.get(channel) ?? new Set<EventListener>();
    listeners.add(listener); this.subscribers.set(channel, listeners);
    return () => { listeners.delete(listener); if (!listeners.size) this.subscribers.delete(channel); };
  }
  publish(channel: string, name: string, value: unknown): void {
    if (!this.disposed) for (const listener of this.subscribers.get(channel) ?? []) listener(name, value);
  }
  agentspace(event: AgentspaceEvent): void {
    this.publish("agentspace", "agentspace", event);
    this.broadcast({ type: "agentspace_event", agentspace_event: event });
  }
  schedule(callback: () => void, delay: number): () => void {
    const timer = setTimeout(() => { this.timers.delete(timer); if (!this.disposed) callback(); }, delay);
    this.timers.add(timer);
    return () => { clearTimeout(timer); this.timers.delete(timer); };
  }
  enqueue(sessionId: string, action: (signal: AbortSignal) => Promise<void>, onError: (error: unknown) => void): void {
    const generation = this.generations.get(sessionId) ?? 0;
    const previous = this.queues.get(sessionId) ?? Promise.resolve();
    const next = previous.then(async () => {
      if (this.disposed || generation !== (this.generations.get(sessionId) ?? 0)) return;
      // 每次回复独占取消令牌；中断当前回复不丢弃已经接受的后续输入。
      const owner = new AbortController();
      this.tasks.set(sessionId, owner);
      try { await action(owner.signal); }
      catch (error) { if (!owner.signal.aborted) onError(error); }
      finally { if (this.tasks.get(sessionId) === owner) this.tasks.delete(sessionId); }
    });
    this.queues.set(sessionId, next);
    void next.then(() => { if (this.queues.get(sessionId) === next) this.queues.delete(sessionId); });
  }
  cancelSession(sessionId: string, discardQueued = false): void {
    this.tasks.get(sessionId)?.abort();
    if (discardQueued) this.generations.set(sessionId, (this.generations.get(sessionId) ?? 0) + 1);
  }
  dispose(): void {
    this.disposed = true;
    for (const timer of this.timers) clearTimeout(timer);
    for (const owner of this.tasks.values()) owner.abort();
    this.timers.clear(); this.tasks.clear(); this.queues.clear();
    for (const socket of [...this.sockets]) socket.terminate(1001);
    this.sockets.clear(); this.subscribers.clear();
  }
}

export function pauseFor(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(new DOMException("Cancelled", "AbortError")); return; }
    const cancel = () => { clearTimeout(timer); signal.removeEventListener("abort", cancel); reject(new DOMException("Cancelled", "AbortError")); };
    const timer = setTimeout(() => { signal.removeEventListener("abort", cancel); resolve(); }, milliseconds);
    signal.addEventListener("abort", cancel, { once: true });
  });
}
