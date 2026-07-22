/**
 * ExpectationHeatmap — shows confirmed reader expectations grouped by status.
 *
 * Uses echarts bar chart. The "heatmap" metaphor here is a status distribution
 * across the expectation ledger: how many expectations are opened, strengthened,
 * partially/fully paid, or invalidated.
 */

import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

import type { Expectation } from "../../api/client";

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer]);

// ── Status config ─────────────────────────────────────────────────────────

const STATUS_ORDER: Expectation["status"][] = [
  "opened",
  "strengthened",
  "partially_paid",
  "paid",
  "invalidated",
];

const STATUS_LABELS: Record<Expectation["status"], string> = {
  opened: "已开启",
  strengthened: "已强化",
  partially_paid: "部分兑现",
  paid: "已兑现",
  invalidated: "已作废",
};

const STATUS_COLORS: Record<Expectation["status"], string> = {
  opened: "#f59e0b",       // amber – attention needed
  strengthened: "#3b82f6", // blue – building tension
  partially_paid: "#8b5cf6",// violet – progress
  paid: "#10b981",         // green – resolved
  invalidated: "#6b7280",  // gray – closed
};

// ── Component ─────────────────────────────────────────────────────────────

interface Props {
  expectations: Expectation[];
}

export function ExpectationHeatmap({ expectations }: Props) {
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!chartRef.current) return;
    if (!instanceRef.current) {
      instanceRef.current = echarts.init(chartRef.current, null, { renderer: "canvas" });
    }
    const chart = instanceRef.current;

    const counts = STATUS_ORDER.map(
      (s) => expectations.filter((e) => e.status === s).length,
    );

    chart.setOption({
      tooltip: {
        trigger: "axis",
        formatter: (params: unknown) => {
          const p = params as Array<{ name: string; value: number }>;
          return p.map((item) => `${item.name}: ${item.value} 条`).join("<br/>");
        },
      },
      grid: { left: 8, right: 8, top: 8, bottom: 4, containLabel: true },
      xAxis: {
        type: "category",
        data: STATUS_ORDER.map((s) => STATUS_LABELS[s]),
        axisLabel: { fontSize: 11, color: "#6b7280" },
        axisTick: { show: false },
        axisLine: { lineStyle: { color: "#e5e7eb" } },
      },
      yAxis: {
        type: "value",
        minInterval: 1,
        axisLabel: { fontSize: 11, color: "#6b7280" },
        splitLine: { lineStyle: { color: "#f3f4f6" } },
      },
      series: [
        {
          type: "bar",
          data: STATUS_ORDER.map((s, i) => ({
            value: counts[i],
            itemStyle: { color: STATUS_COLORS[s], borderRadius: [4, 4, 0, 0] },
          })),
          barMaxWidth: 40,
        },
      ],
    });

    return () => {
      // don't destroy on data change, just re-render
    };
  }, [expectations]);

  // Resize on container size change
  useEffect(() => {
    if (typeof ResizeObserver === "undefined" || !chartRef.current) return;
    const observer = new ResizeObserver(() => instanceRef.current?.resize());
    observer.observe(chartRef.current);
    return () => observer.disconnect();
  }, []);

  if (expectations.length === 0) {
    return (
      <div className="expectation-heatmap expectation-heatmap--empty">
        <p className="muted">期待账本尚无已确认条目。</p>
        <p className="muted small">批准 webnovel-curate-memory 的候选后，期待状态会出现在这里。</p>
      </div>
    );
  }

  // Urgency indicators: expectations open too long without progress
  const urgent = expectations.filter(
    (e) => e.status === "opened" && e.strengthening_event_ids.length === 0,
  );

  return (
    <div className="expectation-heatmap">
      <div ref={chartRef} className="expectation-chart" style={{ height: 140 }} />

      {urgent.length > 0 && (
        <div className="expectation-urgent">
          <strong>⚠ {urgent.length} 条期待尚未强化</strong>
          <ul>
            {urgent.slice(0, 3).map((e) => (
              <li key={e.id} title={e.payoff_semantics}>
                {e.reader_question}
              </li>
            ))}
            {urgent.length > 3 && <li>…还有 {urgent.length - 3} 条</li>}
          </ul>
        </div>
      )}

      <details className="expectation-list-toggle">
        <summary>全部 {expectations.length} 条期待</summary>
        <ul className="expectation-list">
          {expectations.map((e) => (
            <li key={e.id} className={`expectation-item expectation-item--${e.status}`}>
              <span className="expectation-status-dot" />
              <span className="expectation-question">{e.reader_question}</span>
              <span className="expectation-scope">{e.scope === "long_term" ? "长线" : "短线"}</span>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
