import type { TaskStatus } from "../../api/events";

type RunConnection = "connecting" | "connected" | "reconnecting" | "error";

interface RunStatusProps {
  status: TaskStatus;
  connection: RunConnection;
  errorCode?: "EVENT_STREAM_INVALID" | "EVENT_STREAM_UNAVAILABLE";
}

const taskLabels: Record<TaskStatus, string> = {
  pending: "等待开始",
  running: "正在运行",
  awaiting_approval: "等待审批",
  completed: "任务已完成",
  failed: "任务失败",
  cancelled: "任务已取消",
  interrupted: "任务已中断",
};

const connectionLabels: Record<RunConnection, string> = {
  connecting: "正在连接",
  connected: "事件连接正常",
  reconnecting: "正在重新连接",
  error: "事件连接异常",
};

export function RunStatus({ status, connection, errorCode }: RunStatusProps) {
  return (
    <section aria-label="任务状态">
      <strong>{taskLabels[status]}</strong>
      <span>{connectionLabels[connection]}</span>
      {errorCode ? <p role="alert">事件连接异常，请检查服务状态</p> : null}
    </section>
  );
}
