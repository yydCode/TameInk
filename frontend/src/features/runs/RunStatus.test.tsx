import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { RunStatus } from "./RunStatus";

describe("RunStatus", () => {
  afterEach(cleanup);

  it("shows the task and connection state", () => {
    render(<RunStatus status="awaiting_approval" connection="reconnecting" />);

    expect(screen.getByText("等待审批")).toBeInTheDocument();
    expect(screen.getByText("正在重新连接")).toBeInTheDocument();
  });

  it("shows a stable stream error without exposing raw details", () => {
    render(<RunStatus status="interrupted" connection="error" errorCode="EVENT_STREAM_INVALID" />);

    expect(screen.getByText("任务已中断")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("事件连接异常，请检查服务状态");
  });
});
