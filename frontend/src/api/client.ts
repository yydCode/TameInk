export interface HealthResponse {
  status: "ok";
  service: "tame-ink-api";
  version: string;
}

interface HealthRequestOptions {
  signal?: AbortSignal;
}

const HEALTH_REQUEST_TIMEOUT_MS = 5_000;

function isHealthResponse(value: unknown): value is HealthResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const candidate = value as Record<string, unknown>;
  return (
    candidate.status === "ok" &&
    candidate.service === "tame-ink-api" &&
    typeof candidate.version === "string"
  );
}

export async function getHealth(options: HealthRequestOptions = {}): Promise<HealthResponse> {
  const controller = new AbortController();
  const abortFromCaller = () => controller.abort(options.signal?.reason);
  const timeoutId = setTimeout(() => {
    controller.abort(new DOMException("Health request timed out", "TimeoutError"));
  }, HEALTH_REQUEST_TIMEOUT_MS);

  if (options.signal?.aborted) {
    abortFromCaller();
  } else {
    options.signal?.addEventListener("abort", abortFromCaller, { once: true });
  }

  try {
    const response = await fetch("/api/health", {
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`Health request failed with status ${response.status}`);
    }

    const payload: unknown = await response.json();
    if (!isHealthResponse(payload)) {
      throw new Error("Health response did not match the expected schema");
    }

    return payload;
  } finally {
    clearTimeout(timeoutId);
    options.signal?.removeEventListener("abort", abortFromCaller);
  }
}
