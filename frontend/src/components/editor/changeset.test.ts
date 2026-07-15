import { describe, expect, it } from "vitest";

import { markdownDiff } from "./changeset";

describe("markdownDiff", () => {
  it("keeps equal Markdown unchanged", () => {
    expect(markdownDiff("# 标题", "# 标题")).toEqual([
      { kind: "unchanged", text: "# 标题" },
    ]);
  });

  it("represents replacement as removal and addition", () => {
    expect(markdownDiff("旧句", "新句")).toEqual([
      { kind: "removed", text: "旧句" },
      { kind: "added", text: "新句" },
    ]);
  });
});

