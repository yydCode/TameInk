export const queryKeys = {
  health: ["health"] as const,
  projects: ["projects"] as const,
  project: (projectId: string) => ["project", projectId] as const,
  snapshot: (projectId: string) => ["snapshot", projectId] as const,
  workflow: (projectId: string) => ["workflow", projectId] as const,
  tasks: (projectId: string) => ["tasks", projectId] as const,
  task: (projectId: string, taskId: string) => ["task", projectId, taskId] as const,
  taskLogs: (projectId: string, taskId: string, level: string) =>
    ["task-logs", projectId, taskId, level] as const,
  document: (projectId: string, path: string) => ["document", projectId, path] as const,
  commercial: (projectId: string) => ["commercial", projectId] as const,
  memory: (projectId: string) => ["memory", projectId] as const,
  usage: (projectId: string) => ["usage", projectId] as const,
  revisions: (projectId: string) => ["revisions", projectId] as const,
};
