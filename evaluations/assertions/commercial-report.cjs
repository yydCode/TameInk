const DIMENSIONS = new Set([
  "opening_urgency",
  "reader_promise",
  "emotional_payoff",
  "conflict_escalation",
  "information_clarity",
  "chapter_hook",
  "differentiation",
]);

module.exports = (output, context) => {
  try {
    const report = JSON.parse(output);
    const scores = Array.isArray(report.dimensions) ? report.dimensions : [];
    const observed = new Set(scores.map((item) => item.dimension));
    const schemaValid =
      scores.length === DIMENSIONS.size &&
      observed.size === DIMENSIONS.size &&
      [...observed].every((dimension) => DIMENSIONS.has(dimension)) &&
      scores.every(
        (item) =>
          Number.isInteger(item.score) &&
          item.score >= 0 &&
          item.score <= 100 &&
          typeof item.reason === "string" &&
          item.reason.trim(),
      );
    const mean = scores.length
      ? Math.round(scores.reduce((total, item) => total + item.score, 0) / scores.length)
      : -1;
    const issues = Array.isArray(report.issues) ? report.issues : [];
    const citationsValid = issues.every((issue) => {
      const match = /^chars:(\d+)-(\d+)$/.exec(issue.citation?.location ?? "");
      if (!match || typeof issue.citation?.quote !== "string") return false;
      const start = Number(match[1]);
      const end = Number(match[2]);
      return start < end && context.vars.candidate.slice(start, end) === issue.citation.quote;
    });
    const scoreByDimension = Object.fromEntries(
      scores.map((item) => [item.dimension, item.score]),
    );
    const expectedLowDimensions = String(context.vars.expectedLowDimensions ?? "")
      .split(",")
      .filter(Boolean);
    const lowDimensionsValid = expectedLowDimensions.every(
      (dimension) => scoreByDimension[dimension] <= 50,
    );
    const pass =
      schemaValid &&
      report.total_score === mean &&
      report.recommendation === context.vars.expectedRecommendation &&
      citationsValid &&
      lowDimensionsValid;
    return {
      pass,
      score: [schemaValid, report.total_score === mean, citationsValid, lowDimensionsValid]
        .filter(Boolean).length / 4,
      reason: pass
        ? "商业报告结构、证据和预期判断一致"
        : `商业报告失败：schema=${schemaValid}, mean=${report.total_score === mean}, decision=${report.recommendation === context.vars.expectedRecommendation}, citations=${citationsValid}, lowDimensions=${lowDimensionsValid}`,
      namedScores: {
        schema: schemaValid ? 1 : 0,
        citations: citationsValid ? 1 : 0,
        expectedDecision:
          report.recommendation === context.vars.expectedRecommendation ? 1 : 0,
      },
    };
  } catch (error) {
    return { pass: false, score: 0, reason: `invalid JSON: ${error.message}` };
  }
};
