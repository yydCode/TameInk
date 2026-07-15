import { describe, expect, it } from "vitest";

import { applyReview, reviewChanges } from "./changeset";

describe("reviewChanges", () => {
  it("keeps equal Markdown unchanged", () => {
    expect(reviewChanges("# 标题", "# 标题")).toEqual([]);
  });

  it("creates independently reviewable changes", () => {
    const changes = reviewChanges("旧句。中段。旧尾。", "新句。中段。新尾。");
    expect(changes).toHaveLength(2);
    expect(changes.map((change) => [change.before, change.after])).toEqual([
      ["旧", "新"],
      ["旧", "新"],
    ]);
    expect(applyReview("旧句。中段。旧尾。", "新句。中段。新尾。", new Set(["change-1"]))).toBe(
      "新句。中段。旧尾。",
    );
  });
});
