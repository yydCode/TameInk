import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

describe("App", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("shows the application title and an explicit offline status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    render(<App />);

    expect(screen.getByRole("heading", { name: "Tame Ink" })).toBeInTheDocument();
    expect(await screen.findByText("后端离线")).toBeInTheDocument();
  });

  it("shows the backend as offline when the health request times out", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("The operation was aborted", "AbortError"));
          });
        });
      }),
    );

    render(<App />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });

    expect(screen.getByText("后端离线")).toBeInTheDocument();
  });

  it("cancels the health request when the application unmounts", () => {
    let requestSignal: AbortSignal | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
        requestSignal = init?.signal ?? undefined;
        return new Promise<Response>(() => undefined);
      }),
    );

    const { unmount } = render(<App />);
    unmount();

    expect(requestSignal?.aborted).toBe(true);
  });

  it("opens the project creation workflow", () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "创建第一部作品" }));

    expect(screen.getByRole("heading", { name: "建立你的故事" })).toBeInTheDocument();
    expect(screen.getByLabelText("项目 ID")).toHaveValue("my-novel");
    expect(screen.getByRole("button", { name: "创建并进入工作台" })).toBeInTheDocument();
  });
});
