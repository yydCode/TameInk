import { useMemo, useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  Copy,
  RefreshCw,
  RotateCcw,
  XCircle,
} from "lucide-react";
import { useParams } from "react-router";

import {
  getProjectUsage,
  getTaskLogs,
  getTaskHistory,
  getTaskRun,
  retryTask,
  transitionTask,
  type Task,
  type TaskDiagnosticLog,
  type TaskLogLevel,
} from "../api/client";
import { queryKeys } from "../app/queryKeys";
import { RunStatus } from "../features/runs/RunStatus";
import { useProjectWorkspace } from "../features/workspace/useProjectWorkspace";
import { useTaskStream } from "../hooks/useTaskStream";

const pageSize = 12;

export function RunsPage() {
  const { projectId = "" } = useParams();
  const queryClient = useQueryClient();
  const { tasks } = useProjectWorkspace(projectId);
  const usage = useQuery({
    queryKey: queryKeys.usage(projectId),
    queryFn: () => getProjectUsage(projectId),
  });
  const [purpose, setPurpose] = useState<Task["purpose"] | "all">("all");
  const [status, setStatus] = useState<Task["status"] | "all">("all");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [logLevel, setLogLevel] = useState<TaskLogLevel | "all">("all");
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const selectedTask = tasks.data?.find((task) => task.id === selected);
  const history = useQuery({
    queryKey: ["task-history", projectId, selected],
    queryFn: () => getTaskHistory(projectId, selected!),
    enabled: Boolean(selected),
  });
  const run = useQuery({
    queryKey: ["task-run", projectId, selected],
    queryFn: () => getTaskRun(projectId, selected!),
    enabled: Boolean(selected),
  });
  const logs = useInfiniteQuery({
    queryKey: queryKeys.taskLogs(projectId, selected ?? "", logLevel),
    queryFn: ({ pageParam }) =>
      getTaskLogs(projectId, selected!, {
        afterId: pageParam,
        level: logLevel === "all" ? undefined : logLevel,
      }),
    initialPageParam: 0,
    getNextPageParam: (last) => last.next_after_id ?? undefined,
    enabled: Boolean(selected),
    refetchInterval: selectedTask && ["pending", "running"].includes(selectedTask.status)
      ? 3_000
      : false,
  });
  const stream = useTaskStream(
    projectId,
    selectedTask && ["pending", "running"].includes(selectedTask.status)
      ? selectedTask.id
      : undefined,
  );
  const filtered = useMemo(
    () =>
      tasks.data?.filter(
        (task) =>
          (purpose === "all" || task.purpose === purpose) &&
          (status === "all" || task.status === status),
      ) ?? [],
    [purpose, status, tasks.data],
  );
  const visible = filtered.slice(page * pageSize, page * pageSize + pageSize);
  const action = useMutation({
    mutationFn: ({ task, kind }: { task: Task; kind: "cancel" | "retry" }) =>
      kind === "cancel"
        ? transitionTask(projectId, task.id, "cancel")
        : retryTask(projectId, task.id),
    onSuccess: (task) => {
      setSelected(task.id);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.tasks(projectId),
      });
    },
  });
  const purposeLabels: Record<Task["purpose"], string> = {
    manual: "手动",
    setting: "故事设定",
    commercial: "商业定位",
    book_outline: "全书大纲",
    volume_outline: "分卷大纲",
    chapter: "章节",
    import: "导入",
    commercial_audit: "商业复审",
    memory_curation: "记忆整理",
    export: "导出",
  };
  const diagnosticLogs = logs.data?.pages.flatMap((page) => page.items) ?? [];

  async function copyDiagnostics() {
    if (!selectedTask || !navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(
        JSON.stringify(
          {
            task_id: selectedTask.id,
            purpose: selectedTask.purpose,
            status: selectedTask.status,
            error_code: selectedTask.error_code,
            logs: diagnosticLogs,
          },
          null,
          2,
        ),
      );
      setCopyStatus("已复制安全诊断摘要");
    } catch {
      setCopyStatus("复制失败，请检查浏览器权限");
    }
  }
  return (
    <div className="runs-page">
      <header className="project-heading">
        <div>
          <span className="eyebrow">运行记录</span>
          <h1>任务与模型调用</h1>
          <p>失败任务保留原记录，重试始终创建新的关联任务。</p>
        </div>
        <div className="usage-summary">
          <strong>
            {usage.data?.total_tokens.toLocaleString("zh-CN") ?? 0}
          </strong>
          <span>
            tokens · ¥{usage.data?.total_cost_cny.toFixed(4) ?? "0.0000"}
          </span>
        </div>
      </header>
      <div className="run-filters">
        <select
          aria-label="任务类型"
          value={purpose}
          onChange={(event) => {
            setPurpose(event.target.value as typeof purpose);
            setPage(0);
          }}
        >
          <option value="all">全部类型</option>
          {Object.entries(purposeLabels).map(([value, label]) => (
            <option value={value} key={value}>
              {label}
            </option>
          ))}
        </select>
        <select
          aria-label="任务状态"
          value={status}
          onChange={(event) => {
            setStatus(event.target.value as typeof status);
            setPage(0);
          }}
        >
          <option value="all">全部状态</option>
          {[
            "pending",
            "running",
            "awaiting_approval",
            "completed",
            "failed",
            "cancelled",
            "interrupted",
          ].map((value) => (
            <option key={value}>{value}</option>
          ))}
        </select>
        <button
          className="icon-button"
          type="button"
          onClick={() => void tasks.refetch()}
          aria-label="刷新任务"
          title="刷新任务"
        >
          <RefreshCw size={16} />
        </button>
      </div>
      <div className="runs-layout">
        <section className="run-table">
          {visible.map((task) => (
            <article
              key={task.id}
              className={selected === task.id ? "is-active" : ""}
            >
              <button
                className="run-select"
                type="button"
                onClick={() => setSelected(task.id)}
              >
                <span>
                  <strong>{purposeLabels[task.purpose]}</strong>
                  <small>{task.subject_id ?? task.id.slice(0, 8)}</small>
                </span>
                <RunStatus
                  status={task.status}
                  connection={
                    selected === task.id ? stream.connection : "connected"
                  }
                />
                <time>{new Date(task.updated_at).toLocaleString("zh-CN")}</time>
              </button>
              <span className="row-actions">
                {["failed", "cancelled", "interrupted"].includes(
                  task.status,
                ) && (
                  <button
                    className="icon-button"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      action.mutate({ task, kind: "retry" });
                    }}
                    aria-label="重试任务"
                    title="重试任务"
                  >
                    <RotateCcw size={15} />
                  </button>
                )}
                {["pending", "running", "awaiting_approval"].includes(
                  task.status,
                ) && (
                  <button
                    className="icon-button"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      action.mutate({ task, kind: "cancel" });
                    }}
                    aria-label="取消任务"
                    title="取消任务"
                  >
                    <XCircle size={15} />
                  </button>
                )}
              </span>
            </article>
          ))}
          <div className="pagination">
            <button
              className="icon-button"
              type="button"
              disabled={page === 0}
              onClick={() => setPage((value) => value - 1)}
              aria-label="上一页"
            >
              <ChevronLeft size={15} />
            </button>
            <span>
              {page + 1} / {Math.max(1, Math.ceil(filtered.length / pageSize))}
            </span>
            <button
              className="icon-button"
              type="button"
              disabled={(page + 1) * pageSize >= filtered.length}
              onClick={() => setPage((value) => value + 1)}
              aria-label="下一页"
            >
              <ChevronRight size={15} />
            </button>
          </div>
        </section>
        <aside className="run-detail">
          {selectedTask ? (
            <>
              <h2>{purposeLabels[selectedTask.purpose]}</h2>
              <dl>
                <div>
                  <dt>状态</dt>
                  <dd>{selectedTask.status}</dd>
                </div>
                <div>
                  <dt>耗时</dt>
                  <dd>
                    {selectedTask.duration_ms === null
                      ? "-"
                      : `${selectedTask.duration_ms} ms`}
                  </dd>
                </div>
                <div>
                  <dt>错误</dt>
                  <dd>{selectedTask.error_code ?? "无"}</dd>
                </div>
                <div>
                  <dt>重试来源</dt>
                  <dd>{selectedTask.retry_of_task_id?.slice(0, 12) ?? "无"}</dd>
                </div>
              </dl>
              <h3>Agent trace</h3>
              {run.data?.agent_runs.map((item) => (
                <div className="trace-row" key={`${item.agent}-${item.stage}`}>
                  <strong>{item.agent}</strong>
                  <span>
                    {item.stage} · {item.duration_ms} ms
                  </span>
                  <code>{item.skill}</code>
                </div>
              ))}
              <h3>事件</h3>
              <ol className="event-history">
                {history.data?.map((event) => (
                  <li key={event.sequence}>
                    <span>{event.sequence}</span>
                    <strong>{event.type}</strong>
                    <time>
                      {new Date(event.timestamp).toLocaleTimeString("zh-CN")}
                    </time>
                  </li>
                ))}
              </ol>
              <div className="diagnostic-heading">
                <h3>诊断日志</h3>
                <div>
                  <select
                    aria-label="日志级别"
                    value={logLevel}
                    onChange={(event) => {
                      setLogLevel(event.target.value as TaskLogLevel | "all");
                      setCopyStatus(null);
                    }}
                  >
                    <option value="all">全部级别</option>
                    <option value="info">信息</option>
                    <option value="warning">警告</option>
                    <option value="error">错误</option>
                  </select>
                  <button
                    className="icon-button"
                    type="button"
                    aria-label="复制诊断摘要"
                    title="复制诊断摘要"
                    onClick={() => void copyDiagnostics()}
                  >
                    <Copy size={14} />
                  </button>
                </div>
              </div>
              {copyStatus && <p className="diagnostic-status">{copyStatus}</p>}
              <ol className="diagnostic-log-list" aria-label="诊断日志时间线">
                {diagnosticLogs.map((entry) => (
                  <DiagnosticLogRow entry={entry} key={entry.id} />
                ))}
              </ol>
              {logs.hasNextPage && (
                <button
                  className="button button-secondary diagnostic-more"
                  type="button"
                  disabled={logs.isFetchingNextPage}
                  onClick={() => void logs.fetchNextPage()}
                >
                  {logs.isFetchingNextPage ? "读取中..." : "加载更多日志"}
                </button>
              )}
              {logs.isPending && <p className="muted">读取诊断日志...</p>}
              {logs.isError && <p className="inline-error">诊断日志读取失败</p>}
            </>
          ) : (
            <div className="editor-empty">选择任务查看 trace、错误和事件。</div>
          )}
        </aside>
      </div>
    </div>
  );
}

const eventLabels: Record<string, string> = {
  "task.created": "任务已创建",
  "task.status_changed": "任务状态已变更",
  "task.cancel_requested": "已请求取消任务",
  "task.error_recorded": "已记录任务错误",
  "queue.enqueued": "已进入任务队列",
  "worker.claimed": "Worker 已接收任务",
  "worker.completed": "Worker 已完成任务",
  "worker.cancelled": "Worker 已取消任务",
  "worker.failed": "Worker 执行失败",
  "agent.stage.started": "Agent 阶段开始",
  "agent.stage.completed": "Agent 阶段完成",
  "agent.stage.failed": "Agent 阶段失败",
  "workflow.candidate_written": "候选产物已写入",
  "workflow.chapter_candidate_written": "章节候选已写入",
  "workflow.chapter_confirmed": "正式章节已确认",
  "workflow.commercial_report_written": "商业审查报告已写入",
};

function DiagnosticLogRow({ entry }: { entry: TaskDiagnosticLog }) {
  return (
    <li className={`diagnostic-log diagnostic-log--${entry.level}`}>
      <div>
        <strong>{eventLabels[entry.event] ?? entry.event}</strong>
        <span>{entry.agent ?? entry.component}</span>
        <time>{new Date(entry.timestamp).toLocaleTimeString("zh-CN")}</time>
      </div>
      {Object.keys(entry.details).length > 0 && (
        <dl>
          {Object.entries(entry.details).map(([key, value]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>{Array.isArray(value) ? value.join(", ") : String(value)}</dd>
            </div>
          ))}
        </dl>
      )}
    </li>
  );
}
