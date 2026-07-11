import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

describe("App", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the application title and an explicit offline status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    render(<App />);

    expect(screen.getByRole("heading", { name: "Tame Ink" })).toBeInTheDocument();
    expect(await screen.findByText("后端离线")).toBeInTheDocument();
  });
});
