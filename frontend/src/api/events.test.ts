import { describe, expect, it, vi } from "vitest";

import { parseSseMessages, subscribeTaskEvents } from "./events";

const event = (sequence: number) => ({
  task_id: "00000000-0000-4000-8000-000000000001",
  project_id: "story-01",
  sequence,
  type: sequence === 1 ? "task.created" : "task.started",
  timestamp: "2026-07-11T12:00:00+00:00",
  data: {},
});

const frame = (sequence: number) =>
  `id: ${sequence}\nevent: ${event(sequence).type}\ndata: ${JSON.stringify(event(sequence))}\n\n`;

function response(body: string): Response {
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

describe("task event stream", () => {
  it("parses strict SSE id, event and JSON data", () => {
    expect(parseSseMessages(frame(1))).toEqual([{ id: 1, event: "task.created", data: event(1) }]);
  });

  it.each([
    "event: task.created\ndata: {}\n\n",
    "id: -1\nevent: task.created\ndata: {}\n\n",
    "id: 1\nevent: task.created\ndata: not-json\n\n",
    `id: 1\nevent: task.started\ndata: ${JSON.stringify(event(1))}\n\n`,
  ])("reports malformed events instead of accepting them", (input) => {
    expect(() => parseSseMessages(input)).toThrowError();
  });

  it("reconnects with the last id and does not deliver duplicates", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(response(frame(1)))
      .mockResolvedValueOnce(response(frame(1) + frame(2)));
    const received: number[] = [];
    const subscription = subscribeTaskEvents("story-01", event(1).task_id, {
      fetcher,
      reconnectDelayMs: 0,
      onEvent: (message) => {
        received.push(message.id);
        if (message.id === 2) subscription.cancel();
      },
      onError: (error) => {
        throw error;
      },
      onConnectionChange: vi.fn(),
    });

    await subscription.done;

    expect(received).toEqual([1, 2]);
    expect(fetcher).toHaveBeenNthCalledWith(
      2,
      expect.any(String),
      expect.objectContaining({ headers: expect.objectContaining({ "Last-Event-ID": "1" }) }),
    );
    expect(fetcher.mock.calls.every((call) => call[1]?.method === "GET")).toBe(true);
  });

  it("can be cancelled and aborts the active request", async () => {
    let signal: AbortSignal | undefined;
    const fetcher = vi.fn<typeof fetch>((_url, init) => {
      signal = init?.signal ?? undefined;
      return new Promise<Response>((_resolve, reject) => {
        signal?.addEventListener("abort", () => reject(signal?.reason), { once: true });
      });
    });
    const subscription = subscribeTaskEvents("story-01", event(1).task_id, {
      fetcher,
      onEvent: vi.fn(),
      onError: vi.fn(),
      onConnectionChange: vi.fn(),
    });

    subscription.cancel();
    await subscription.done;

    expect(signal?.aborted).toBe(true);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
