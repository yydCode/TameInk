import { useQuery } from "@tanstack/react-query";

import {
  getProject,
  getProjectSnapshot,
  getWorkflowStatus,
  listTasks,
} from "../../api/client";
import { queryKeys } from "../../app/queryKeys";

export function useProjectWorkspace(projectId: string) {
  const project = useQuery({
    queryKey: queryKeys.project(projectId),
    queryFn: () => getProject(projectId),
  });
  const snapshot = useQuery({
    queryKey: queryKeys.snapshot(projectId),
    queryFn: () => getProjectSnapshot(projectId),
  });
  const workflow = useQuery({
    queryKey: queryKeys.workflow(projectId),
    queryFn: () => getWorkflowStatus(projectId),
  });
  const tasks = useQuery({
    queryKey: queryKeys.tasks(projectId),
    queryFn: () => listTasks(projectId),
    refetchInterval: 3_000,
  });
  return { project, snapshot, workflow, tasks };
}
