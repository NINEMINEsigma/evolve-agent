import { describe, expect, it } from "vitest";
import { ChatTelemetryController } from "./chatTelemetry";

describe("ChatTelemetryController", () => {
  it("does not record while disabled and removes unknown fields", () => {
    const controller = new ChatTelemetryController();
    controller.record({ time: Date.now(), kind: "stream_batch", charCount: 2 });
    expect(controller.snapshot().eventCount).toBe(0);
    controller.start();
    controller.record({
      time: Date.now(),
      kind: "stream_batch",
      charCount: 2,
      secret: "message body",
    } as never);
    expect(controller.snapshot().eventCount).toBeGreaterThan(0);
    controller.stop();
    const count = controller.snapshot().eventCount;
    controller.record({ time: Date.now(), kind: "stream_batch" });
    expect(controller.snapshot().eventCount).toBe(count);
  });
});
