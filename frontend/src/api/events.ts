export type TaskStatus =
  | "pending"
  | "running"
  | "awaiting_approval"
  | "completed"
  | "failed"
  | "cancelled"
  | "interrupted";

export interface TaskEvent {
  task_id: string;
  project_id: string;
  sequence: number;
  type: string;
  timestamp: string;
  data: Record<string, unknown>;
}

export interface SseMessage {
  id: number;
  event: string;
  data: TaskEvent;
}

export type EventConnection = "connecting" | "connected" | "reconnecting" | "error";

interface SubscribeOptions {
  onEvent: (message: SseMessage) => void;
  onError: (error: Error) => void;
  onConnectionChange: (connection: EventConnection) => void;
  fetcher?: typeof fetch;
  reconnectDelayMs?: number;
  lastEventId?: number;
}

export interface EventSubscription {
  cancel: () => void;
  done: Promise<void>;
}

export class EventStreamError extends Error {
  readonly code: string;
  readonly details: unknown;
  readonly status: number;
  readonly retryable: boolean;

  constructor(
    code: string,
    message: string,
    status: number,
    details: unknown,
    retryable: boolean,
  ) {
    super(message);
    this.name = "EventStreamError";
    this.code = code;
    this.details = details;
    this.status = status;
    this.retryable = retryable;
  }
}

const TASK_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const PROJECT_ID = /^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$/;
const EVENT_KEYS = ["data", "project_id", "sequence", "task_id", "timestamp", "type"];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseTaskEvent(value: unknown): TaskEvent {
  if (!isRecord(value) || Object.keys(value).sort().join(",") !== EVENT_KEYS.join(",")) {
    throw new Error("EVENT_STREAM_INVALID: event data fields are invalid");
  }
  if (
    typeof value.task_id !== "string" ||
    !TASK_ID.test(value.task_id) ||
    typeof value.project_id !== "string" ||
    !PROJECT_ID.test(value.project_id) ||
    !Number.isSafeInteger(value.sequence) ||
    (value.sequence as number) <= 0 ||
    typeof value.type !== "string" ||
    value.type.trim() !== value.type ||
    value.type.length === 0 ||
    typeof value.timestamp !== "string" ||
    Number.isNaN(Date.parse(value.timestamp)) ||
    !isRecord(value.data)
  ) {
    throw new Error("EVENT_STREAM_INVALID: event data schema is invalid");
  }
  return value as unknown as TaskEvent;
}

export function parseSseMessages(input: string): SseMessage[] {
  const normalized = input.replace(/\r\n|\r/g, "\n");
  if (!normalized.endsWith("\n\n")) {
    throw new Error("EVENT_STREAM_INVALID: incomplete event frame");
  }
  return normalized
    .slice(0, -2)
    .split("\n\n")
    .map((block) => {
      const fields = new Map<string, string>();
      const dataLines: string[] = [];
      for (const line of block.split("\n")) {
        const separator = line.indexOf(":");
        if (separator <= 0) throw new Error("EVENT_STREAM_INVALID: malformed SSE field");
        const key = line.slice(0, separator);
        const rawValue = line.slice(separator + 1);
        const value = rawValue.startsWith(" ") ? rawValue.slice(1) : rawValue;
        if (key === "data") {
          dataLines.push(value);
        } else {
          if (fields.has(key)) throw new Error("EVENT_STREAM_INVALID: duplicate SSE field");
          fields.set(key, value);
        }
      }
      if (fields.size !== 2 || !fields.has("id") || !fields.has("event") || dataLines.length === 0) {
        throw new Error("EVENT_STREAM_INVALID: required SSE fields are missing");
      }
      const rawId = fields.get("id") ?? "";
      if (!/^[1-9][0-9]*$/.test(rawId)) throw new Error("EVENT_STREAM_INVALID: invalid event id");
      const id = Number(rawId);
      if (!Number.isSafeInteger(id)) throw new Error("EVENT_STREAM_INVALID: invalid event id");
      let decoded: unknown;
      try {
        decoded = JSON.parse(dataLines.join("\n"));
      } catch (cause) {
        throw new Error("EVENT_STREAM_INVALID: invalid event JSON", { cause });
      }
      const data = parseTaskEvent(decoded);
      const event = fields.get("event") ?? "";
      if (data.sequence !== id || data.type !== event) {
        throw new Error("EVENT_STREAM_INVALID: SSE metadata does not match event data");
      }
      return { id, event, data };
    });
}

function delay(milliseconds: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.resolve();
  return new Promise((resolve) => {
    const finish = () => {
      clearTimeout(timeout);
      signal.removeEventListener("abort", onAbort);
      resolve();
    };
    const onAbort = () => finish();
    const timeout = setTimeout(finish, milliseconds);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

async function responseError(response: Response): Promise<EventStreamError> {
  if (response.status >= 400 && response.status < 500) {
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      payload = undefined;
    }
    if (isRecord(payload) && isRecord(payload.error)) {
      const code = payload.error.code;
      const message = payload.error.message;
      if (typeof code === "string" && code.length > 0 && typeof message === "string") {
        return new EventStreamError(code, message, response.status, payload.error.details, false);
      }
    }
    return new EventStreamError(
      "EVENT_STREAM_CLIENT_ERROR",
      `Event stream request failed with status ${response.status}`,
      response.status,
      undefined,
      false,
    );
  }
  return new EventStreamError(
    "EVENT_STREAM_UNAVAILABLE",
    `Event stream request failed with status ${response.status}`,
    response.status,
    undefined,
    true,
  );
}

function frameBoundary(input: string): { index: number; length: number } | undefined {
  const match = /\r\n\r\n|\n\n|\r\r/.exec(input);
  return match ? { index: match.index, length: match[0].length } : undefined;
}

export function subscribeTaskEvents(
  projectId: string,
  taskId: string,
  options: SubscribeOptions,
): EventSubscription {
  const controller = new AbortController();
  const fetcher = options.fetcher ?? fetch;
  const reconnectDelayMs = options.reconnectDelayMs ?? 1_000;
  const initialLastId = options.lastEventId ?? 0;
  if (!Number.isSafeInteger(initialLastId) || initialLastId < 0) {
    throw new Error("lastEventId must be a non-negative safe integer");
  }
  let lastId = initialLastId;

  const done = (async () => {
    options.onConnectionChange("connecting");
    while (!controller.signal.aborted) {
      let response: Response | undefined;
      let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
      let stop = false;
      try {
        const headers: Record<string, string> = { Accept: "text/event-stream" };
        if (lastId > 0) headers["Last-Event-ID"] = String(lastId);
        response = await fetcher(
          `/api/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}/events`,
          { method: "GET", headers, signal: controller.signal },
        );
        if (!response.ok) {
          throw await responseError(response);
        }
        if (!response.body) {
          throw new Error("EVENT_STREAM_UNAVAILABLE: response body is missing");
        }
        options.onConnectionChange("connected");
        reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (!controller.signal.aborted) {
          const result = await reader.read();
          buffer += decoder.decode(result.value, { stream: !result.done });
          let boundary = frameBoundary(buffer);
          while (boundary) {
            const frame = buffer.slice(0, boundary.index + boundary.length);
            buffer = buffer.slice(boundary.index + boundary.length);
            for (const message of parseSseMessages(frame)) {
              if (message.id <= lastId) continue;
              if (message.id !== lastId + 1) {
                throw new Error("EVENT_STREAM_INVALID: event sequence contains a gap");
              }
              lastId = message.id;
              try {
                options.onEvent(message);
              } catch (cause) {
                throw new EventStreamError(
                  "EVENT_STREAM_CONSUMER_ERROR",
                  "Event stream consumer rejected an event",
                  0,
                  cause,
                  false,
                );
              }
            }
            boundary = frameBoundary(buffer);
          }
          if (result.done) {
            if (buffer.length > 0) throw new Error("EVENT_STREAM_INVALID: incomplete event frame");
            break;
          }
        }
      } catch (error) {
        if (controller.signal.aborted) break;
        const normalized = error instanceof Error ? error : new Error("EVENT_STREAM_UNAVAILABLE");
        options.onConnectionChange("error");
        options.onError(normalized);
        if (
          normalized.message.startsWith("EVENT_STREAM_INVALID") ||
          (normalized instanceof EventStreamError && !normalized.retryable)
        ) {
          stop = true;
        }
      } finally {
        if (reader) {
          try {
            await reader.cancel();
          } catch {
            // Cleanup failure must not replace the stream error.
          }
          try {
            reader.releaseLock();
          } catch {
            // A reader may already have released its lock.
          }
        } else if (response?.body) {
          try {
            await response.body.cancel();
          } catch {
            // Cleanup failure must not replace the response error.
          }
        }
      }
      if (stop) break;
      if (!controller.signal.aborted) {
        options.onConnectionChange("reconnecting");
        await delay(reconnectDelayMs, controller.signal);
      }
    }
  })();

  return { cancel: () => controller.abort(), done };
}
