import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  RotateCcw,
  XCircle,
} from "lucide-react";
import { useParams } from "react-router";

import {
  getProjectUsage,
  getTaskHistory,
  getTaskRun,
  retryTask,
  transitionTask,
  type Task,
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
            </>
          ) : (
            <div className="editor-empty">选择任务查看 trace、错误和事件。</div>
          )}
        </aside>
      </div>
    </div>
  );
}
