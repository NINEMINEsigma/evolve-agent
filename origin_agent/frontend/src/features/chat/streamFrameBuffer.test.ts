import { afterEach, describe, expect, it, vi } from "vitest";
import { createStreamFrameBuffer } from "./streamFrameBuffer";

const callbacks = new Map<number, FrameRequestCallback>();
let nextFrame = 1;

vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
  const id = nextFrame++;
  callbacks.set(id, callback);
  return id;
});
vi.stubGlobal("cancelAnimationFrame", (id: number) => callbacks.delete(id));

afterEach(() => callbacks.clear());

describe("StreamFrameBuffer", () => {
  it("coalesces deltas into one animation-frame commit", () => {
    const commits = vi.fn();
    const buffer = createStreamFrameBuffer(commits);
    buffer.push({ type: "stream_delta", stream_id: "s", delta: "a" });
    buffer.push({ type: "stream_delta", stream_id: "s", delta: "b" });
    expect(commits).not.toHaveBeenCalled();
    callbacks.values().next().value?.(0);
    expect(commits).toHaveBeenCalledTimes(1);
    expect(commits.mock.calls[0][0].delta).toBe("ab");
  });

  it("flushes before a different stream", () => {
    const commits = vi.fn();
    const buffer = createStreamFrameBuffer(commits);
    buffer.push({ type: "stream_delta", stream_id: "a", delta: "a" });
    buffer.push({ type: "stream_delta", stream_id: "b", delta: "b" });
    expect(commits).toHaveBeenCalledWith(expect.objectContaining({ streamId: "a" }));
  });
});
