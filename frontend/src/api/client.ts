export interface HealthResponse {
  status: "ok";
  service: "tame-ink-api";
  version: string;
}

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

export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch("/api/health", {
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    throw new Error(`Health request failed with status ${response.status}`);
  }

  const payload: unknown = await response.json();
  if (!isHealthResponse(payload)) {
    throw new Error("Health response did not match the expected schema");
  }

  return payload;
}
