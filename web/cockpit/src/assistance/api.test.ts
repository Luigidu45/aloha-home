// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ageSeconds, type Command, postCommand, savedCommand } from "./api.ts";
import { voiceReason } from "./voice.ts";

const command: Command = { id: "1234567890", session: "session1", version: 4, kind: "confirm" };
afterEach(() => vi.unstubAllGlobals());
beforeEach(() => sessionStorage.clear());
describe("assistance delivery acknowledgement", () => {
  it("keeps the same command across lost acknowledgement and reload/retry", async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new TypeError("network")).mockResolvedValueOnce(
      new Response("{}"),
    );
    vi.stubGlobal("fetch", fetcher);
    await expect(postCommand(command)).rejects.toThrow("network");
    const pending = savedCommand();
    expect(pending).toEqual(command);
    await postCommand(pending!);
    expect(fetcher.mock.calls[0][1].body).toBe(fetcher.mock.calls[1][1].body);
    expect(savedCommand()).toBeNull();
  });
  it("does not keep rejected commands for automatic replay", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "La conversación cambió" }), { status: 409 }),
      ),
    );
    await expect(postCommand(command)).rejects.toThrow("La conversación cambió");
    expect(savedCommand()).toBeNull();
  });
  it("keeps a stalled command for explicit reconciliation", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new DOMException("timeout", "TimeoutError")));
    await expect(postCommand(command)).rejects.toThrow("timeout");
    expect(savedCommand()?.id).toBe(command.id);
  });
  it("marks absent and old camera timestamps stale", () => {
    expect(ageSeconds(100, null)).toBe(Infinity);
    expect(ageSeconds(100, 96)).toBe(4);
    expect(ageSeconds(100, 99)).toBe(1);
  });
  it("requires secure origin before offering microphone capture", () => {
    vi.stubGlobal("isSecureContext", false);
    expect(voiceReason()).toContain("HTTPS");
  });
  it("does not fall back to remote speech recognition", () => {
    vi.stubGlobal("isSecureContext", true);
    vi.stubGlobal("SpeechRecognition", undefined);
    vi.stubGlobal("webkitSpeechRecognition", undefined);
    expect(voiceReason()).toContain("no ofrece dictado local");
  });
});
