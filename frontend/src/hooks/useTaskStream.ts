import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import type { Task } from "../api/client";
import { subscribeTaskEvents, type EventConnection } from "../api/events";
import { queryKeys } from "../app/queryKeys";

const statusByEvent: Record<string, Task["status"]> = {
  "task.created": "pending",
  "task.started": "running",
  "task.generation_started": "running",
  "task.awaiting_approval": "awaiting_approval",
  "task.approved": "running",
  "task.completed": "completed",
  "task.failed": "failed",
  "task.cancelled": "cancelled",
  "task.recovered": "interrupted",
};

export function useTaskStream(projectId?: string, taskId?: string) {
  const queryClient = useQueryClient();
  const [connection, setConnection] = useState<EventConnection>("connecting");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId || !taskId) return;
    const subscription = subscribeTaskEvents(projectId, taskId, {
      onEvent: ({ data }) => {
        const status = statusByEvent[data.type];
        if (status) {
          queryClient.setQueryData<Task>(
            queryKeys.task(projectId, taskId),
            (current) =>
              current
                ? { ...current, status, updated_at: data.timestamp }
                : current,
          );
          void queryClient.invalidateQueries({
            queryKey: queryKeys.tasks(projectId),
          });
        }
      },
      onError: (cause) => setError(cause.message),
      onConnectionChange: setConnection,
    });
    return () => subscription.cancel();
  }, [projectId, queryClient, taskId]);

  return { connection, error };
}
