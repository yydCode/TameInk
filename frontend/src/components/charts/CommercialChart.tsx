import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

import type {
  CommercialMetrics,
  CommercialObservation,
} from "../../api/client";

echarts.use([
  BarChart,
  LineChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
]);

export function CommercialChart({
  metrics,
  observations,
}: {
  metrics: CommercialMetrics;
  observations: CommercialObservation[];
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chart.setOption({
      animationDuration: 300,
      color: ["#50745b", "#b06b45"],
      tooltip: { trigger: "axis" },
      grid: { left: 48, right: 18, top: 26, bottom: 38 },
      xAxis: {
        type: "category",
        data: ["曝光", "打开", "首章完读", "三章完读", "追读"],
        axisLabel: { color: "#68736b" },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: "#68736b" },
        splitLine: { lineStyle: { color: "#e5e8e4" } },
      },
      series: [
        {
          type: "bar",
          barMaxWidth: 34,
          data: [
            metrics.impressions,
            metrics.opens,
            metrics.chapter_one_completions,
            metrics.chapter_three_completions,
            metrics.follows,
          ],
        },
      ],
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [metrics, observations]);
  return (
    <div
      className="commercial-chart"
      ref={ref}
      role="img"
      aria-label={`商业漏斗，共 ${observations.length} 次观测`}
    />
  );
}
