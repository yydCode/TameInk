export const queryKeys = {
  health: ["health"] as const,
  projects: ["projects"] as const,
  project: (projectId: string) => ["project", projectId] as const,
  snapshot: (projectId: string) => ["snapshot", projectId] as const,
  workflow: (projectId: string) => ["workflow", projectId] as const,
  creativeNext: (projectId: string) => ["creative-next", projectId] as const,
  creativeArtifacts: (projectId: string) => ["creative-artifacts", projectId] as const,
  tasks: (projectId: string) => ["tasks", projectId] as const,
  task: (projectId: string, taskId: string) => ["task", projectId, taskId] as const,
  taskLogs: (projectId: string, taskId: string, level: string) =>
    ["task-logs", projectId, taskId, level] as const,
  document: (projectId: string, path: string) => ["document", projectId, path] as const,
  commercial: (projectId: string) => ["commercial", projectId] as const,
  memory: (projectId: string) => ["memory", projectId] as const,
  usage: (projectId: string) => ["usage", projectId] as const,
  revisions: (projectId: string) => ["revisions", projectId] as const,
  // 诊断
  diagnostics: (projectId: string) => ["diagnostics", projectId] as const,
  // 建议
  suggestions: (projectId: string) => ["suggestions", projectId] as const,
  // 推荐
  recommendations: (projectId: string, chapterId: string) =>
    ["recommendations", projectId, chapterId] as const,
  // 期待账本
  expectations: (projectId: string) => ["expectations", projectId] as const,
  // 故事卡列表
  storyCards: (projectId: string) => ["story-cards", projectId] as const,
};
