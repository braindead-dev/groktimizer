"use client";

import { useId, useState } from "react";
import type { MetricPoint } from "@/lib/types";

interface KpiChartProps {
  points: MetricPoint[];
  baseline: number;
  unit: string;
  lowerIsBetter: boolean;
}

export function KpiChart({ points, baseline, unit, lowerIsBetter }: KpiChartProps) {
  const patternId = useId().replace(/:/g, "");
  const [hovered, setHovered] = useState<number | null>(points.length - 1);
  const width = 800;
  const height = 290;
  const padX = 26;
  const padY = 28;
  const values = points.map((point) => point.value);
  const min = Math.min(...values, baseline);
  const max = Math.max(...values, baseline);
  const spread = Math.max(max - min, 1);
  const yMin = min - spread * 0.16;
  const yMax = max + spread * 0.12;

  const coordinates = points.map((point, index) => {
    const x = points.length === 1 ? width / 2 : padX + (index / (points.length - 1)) * (width - padX * 2);
    const y = padY + ((yMax - point.value) / (yMax - yMin)) * (height - padY * 2);
    return { x, y };
  });

  const linePath = coordinates.map(({ x, y }, index) => `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`).join(" ");
  const areaPath = coordinates.length
    ? `${linePath} L ${coordinates.at(-1)?.x} ${height - padY} L ${coordinates[0].x} ${height - padY} Z`
    : "";
  const baselineY = padY + ((yMax - baseline) / (yMax - yMin)) * (height - padY * 2);
  const active = hovered === null ? null : points[hovered];
  const activeCoordinate = hovered === null ? null : coordinates[hovered];

  return (
    <div className="kpi-chart-wrap">
      <div className="chart-legend"><span><i className="legend-dither" /> Best observed</span><span><i className="legend-baseline" /> Baseline {baseline}{unit}</span></div>
      <svg className="kpi-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="KPI values across benchmark points">
        <defs>
          <pattern id={patternId} width="6" height="6" patternUnits="userSpaceOnUse">
            <circle cx="1.5" cy="1.5" r="1.05" fill="currentColor" />
          </pattern>
          <linearGradient id={`${patternId}-fade`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="var(--signal)" stopOpacity="0.18" />
            <stop offset="1" stopColor="var(--signal)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 1, 2, 3].map((line) => {
          const y = padY + (line / 3) * (height - padY * 2);
          return <line className="chart-grid-line" key={line} x1={padX} y1={y} x2={width - padX} y2={y} />;
        })}
        <line className="baseline-line" x1={padX} y1={baselineY} x2={width - padX} y2={baselineY} />
        <path className="chart-area-fade" d={areaPath} fill={`url(#${patternId}-fade)`} />
        <path className="chart-area-dither" d={areaPath} fill={`url(#${patternId})`} />
        <path className="chart-main-line" d={linePath} />
        {coordinates.map(({ x, y }, index) => (
          <g key={points[index].run}>
            <circle
              className="chart-hit-point"
              cx={x}
              cy={y}
              r="14"
              onMouseEnter={() => setHovered(index)}
              onFocus={() => setHovered(index)}
              tabIndex={0}
              aria-label={`${points[index].label}: ${points[index].value}${unit}`}
            />
            <circle className={`chart-point ${hovered === index ? "chart-point-active" : ""}`} cx={x} cy={y} r={hovered === index ? 4 : 2.5} />
          </g>
        ))}
        {active && activeCoordinate ? (
          <g className="chart-tooltip" transform={`translate(${Math.min(Math.max(activeCoordinate.x - 54, 8), width - 116)} ${Math.max(activeCoordinate.y - 58, 8)})`}>
            <rect width="108" height="42" rx="8" />
            <text x="10" y="15">{active.label}</text>
            <text className="tooltip-value" x="10" y="32">{active.value}{unit}</text>
          </g>
        ) : null}
      </svg>
      <div className="chart-axis-labels"><span>Baseline</span><span>{points.length} benchmark points</span><span>{lowerIsBetter ? "Lower is better" : "Higher is better"}</span></div>
    </div>
  );
}
