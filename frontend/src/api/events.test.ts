import { describe, expect, it, vi } from "vitest";

import { EventStreamError, parseSseMessages, subscribeTaskEvents } from "./events";

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

function readerResponse(reads: Array<ReadableStreamReadResult<Uint8Array> | Error>) {
  const read = vi.fn(async () => {
    const next = reads.shift();
    if (next instanceof Error) throw next;
    return next ?? { done: true, value: undefined };
  });
  const cancel = vi.fn(async () => undefined);
  const releaseLock = vi.fn();
  const bodyCancel = vi.fn(async () => undefined);
  const body = { getReader: () => ({ read, cancel, releaseLock }), cancel: bodyCancel };
  return {
    response: { ok: true, status: 200, body } as unknown as Response,
    read,
    cancel,
    releaseLock,
    bodyCancel,
  };
}

describe("task event stream", () => {
  it("parses strict SSE id, event and JSON data", () => {
    expect(parseSseMessages(frame(1))).toEqual([{ id: 1, event: "task.created", data: event(1) }]);
  });

  it("parses CRLF frames and joins multiline data fields", () => {
    const payload = JSON.stringify(event(1));
    const midpoint = payload.indexOf(",") + 1;
    const input = `id: 1\r\nevent: task.created\r\ndata: ${payload.slice(0, midpoint)}\r\ndata: ${payload.slice(midpoint)}\r\n\r\n`;

    expect(parseSseMessages(input)).toEqual([{ id: 1, event: "task.created", data: event(1) }]);
  });

  it("parses CRLF correctly when the line ending is split across chunks", async () => {
    const crlfFrame = frame(1).replaceAll("\n", "\r\n");
    const split = crlfFrame.indexOf("\r\n") + 1;
    const controlled = readerResponse([
      { done: false, value: new TextEncoder().encode(crlfFrame.slice(0, split)) },
      { done: false, value: new TextEncoder().encode(crlfFrame.slice(split)) },
    ]);
    const received: number[] = [];
    const subscription = subscribeTaskEvents("story-01", event(1).task_id, {
      fetcher: vi.fn<typeof fetch>().mockResolvedValue(controlled.response),
      onEvent: (message) => {
        received.push(message.id);
        subscription.cancel();
      },
      onError: vi.fn(),
      onConnectionChange: vi.fn(),
    });

    await subscription.done;

    expect(received).toEqual([1]);
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

  it("rejects a sequence gap without advancing the reconnect cursor", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response(frame(1) + frame(3)));
    const errors: Error[] = [];
    const received: number[] = [];
    const subscription = subscribeTaskEvents("story-01", event(1).task_id, {
      fetcher,
      onEvent: (message) => received.push(message.id),
      onError: (error) => errors.push(error),
      onConnectionChange: vi.fn(),
    });

    await subscription.done;

    expect(errors[0]?.message).toContain("EVENT_STREAM_INVALID");
    expect(received).toEqual([1]);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("requires the next id after an initial non-zero cursor and ignores old duplicates", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response(frame(2) + frame(1)));
    const received: number[] = [];
    const subscription = subscribeTaskEvents("story-01", event(1).task_id, {
      fetcher,
      lastEventId: 1,
      onEvent: (message) => {
        received.push(message.id);
        subscription.cancel();
      },
      onError: vi.fn(),
      onConnectionChange: vi.fn(),
    });

    await subscription.done;

    expect(received).toEqual([2]);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][1]?.headers).toMatchObject({ "Last-Event-ID": "1" });
  });

  it("cancels and releases the reader after a parser error", async () => {
    const controlled = readerResponse([
      { done: false, value: new TextEncoder().encode("invalid\n\n") },
    ]);
    const subscription = subscribeTaskEvents("story-01", event(1).task_id, {
      fetcher: vi.fn<typeof fetch>().mockResolvedValue(controlled.response),
      onEvent: vi.fn(),
      onError: vi.fn(),
      onConnectionChange: vi.fn(),
    });

    await subscription.done;

    expect(controlled.cancel).toHaveBeenCalledTimes(1);
    expect(controlled.releaseLock).toHaveBeenCalledTimes(1);
  });

  it("cancels and releases the reader when onEvent throws", async () => {
    const controlled = readerResponse([
      { done: false, value: new TextEncoder().encode(frame(1)) },
    ]);
    const subscription = subscribeTaskEvents("story-01", event(1).task_id, {
      fetcher: vi.fn<typeof fetch>().mockResolvedValue(controlled.response),
      onEvent: () => { throw new Error("consumer failed"); },
      onError: vi.fn(),
      onConnectionChange: vi.fn(),
    });
    await subscription.done;

    expect(controlled.cancel).toHaveBeenCalled();
    expect(controlled.releaseLock).toHaveBeenCalled();
    expect(controlled.read).toHaveBeenCalledTimes(1);
  });

  it("does not let reader cancellation failure replace a parser error", async () => {
    const controlled = readerResponse([
      { done: false, value: new TextEncoder().encode("invalid\n\n") },
    ]);
    controlled.cancel.mockRejectedValue(new Error("cancel failed"));
    const errors: Error[] = [];
    const subscription = subscribeTaskEvents("story-01", event(1).task_id, {
      fetcher: vi.fn<typeof fetch>().mockResolvedValue(controlled.response),
      onEvent: vi.fn(),
      onError: (error) => errors.push(error),
      onConnectionChange: vi.fn(),
    });

    await subscription.done;

    expect(errors[0]?.message).toContain("EVENT_STREAM_INVALID");
    expect(controlled.releaseLock).toHaveBeenCalled();
  });

  it.each(["network", "server"])("closes the old %s response before reconnecting", async (kind) => {
    const order: string[] = [];
    const first = readerResponse([{ done: true, value: undefined }]);
    first.releaseLock.mockImplementation(() => order.push("released"));
    first.bodyCancel.mockImplementation(async () => { order.push("body-cancelled"); });
    const second = readerResponse([{ done: true, value: undefined }]);
    const fetcher = vi.fn<typeof fetch>(async () => {
      order.push(`fetch-${fetcher.mock.calls.length}`);
      if (fetcher.mock.calls.length === 1) {
        if (kind === "network") throw new TypeError("offline");
        return { ok: false, status: 503, body: first.response.body } as Response;
      }
      setTimeout(() => subscription.cancel(), 0);
      return second.response;
    });
    const subscription = subscribeTaskEvents("story-01", event(1).task_id, {
      fetcher,
      reconnectDelayMs: 0,
      onEvent: vi.fn(),
      onError: vi.fn(),
      onConnectionChange: vi.fn(),
    });

    await subscription.done;

    if (kind === "server") {
      expect(first.bodyCancel).toHaveBeenCalledTimes(1);
      expect(order.indexOf("body-cancelled")).toBeLessThan(order.indexOf("fetch-2"));
    }
    expect(fetcher.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("removes the reconnect abort listener after timeout and abort", async () => {
    vi.useFakeTimers();
    const add = vi.spyOn(AbortSignal.prototype, "addEventListener");
    const remove = vi.spyOn(AbortSignal.prototype, "removeEventListener");
    const fetcher = vi.fn<typeof fetch>().mockRejectedValue(new TypeError("offline"));
    const subscription = subscribeTaskEvents("story-01", event(1).task_id, {
      fetcher,
      reconnectDelayMs: 10,
      onEvent: vi.fn(),
      onError: vi.fn(),
      onConnectionChange: vi.fn(),
    });

    await vi.advanceTimersByTimeAsync(10);
    subscription.cancel();
    await subscription.done;

    const addedAbortHandlers = add.mock.calls.filter(([type]) => type === "abort").length;
    const removedAbortHandlers = remove.mock.calls.filter(([type]) => type === "abort").length;
    expect(removedAbortHandlers).toBe(addedAbortHandlers);
    vi.useRealTimers();
    add.mockRestore();
    remove.mockRestore();
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

  it("preserves a stable 416 error and stops reconnecting with the stale id", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(response(frame(1)))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            error: {
              code: "LAST_EVENT_ID_OUT_OF_RANGE",
              message: "Last-Event-ID exceeds current sequence",
              details: { maximum: 0 },
            },
          }),
          { status: 416, headers: { "Content-Type": "application/json" } },
        ),
      );
    const errors: Error[] = [];
    const subscription = subscribeTaskEvents("story-01", event(1).task_id, {
      fetcher,
      reconnectDelayMs: 0,
      onEvent: vi.fn(),
      onError: (error) => errors.push(error),
      onConnectionChange: vi.fn(),
    });

    await subscription.done;

    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls[1][1]?.headers).toMatchObject({ "Last-Event-ID": "1" });
    expect(errors).toEqual([
      expect.objectContaining({
        code: "LAST_EVENT_ID_OUT_OF_RANGE",
        message: "Last-Event-ID exceeds current sequence",
        details: { maximum: 0 },
        status: 416,
      }),
    ]);
    expect(errors[0]).toBeInstanceOf(EventStreamError);
  });

  it.each([400, 404, 409, 422])("does not retry an explicit stable %i client error", async (status) => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({ error: { code: "CLIENT_REQUEST_INVALID", message: "request rejected" } }),
        { status, headers: { "Content-Type": "application/json" } },
      ),
    );
    const subscription = subscribeTaskEvents("story-01", event(1).task_id, {
      fetcher,
      reconnectDelayMs: 0,
      onEvent: vi.fn(),
      onError: vi.fn(),
      onConnectionChange: vi.fn(),
    });

    await subscription.done;

    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
