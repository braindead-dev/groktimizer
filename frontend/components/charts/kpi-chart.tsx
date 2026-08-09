"use client";

import { useMemo, useState } from "react";
import type { MetricSeries } from "@/lib/types";

interface KpiChartProps {
  series: MetricSeries[];
}

const WIDTH = 800;
const HEIGHT = 286;
const PAD_X = 34;
const PAD_Y = 30;

function improvement(metric: MetricSeries, value: number) {
  const range = Math.abs(metric.best - metric.baseline);
  if (!range) return 0;
  const gain = metric.direction === "higher"
    ? value - metric.baseline
    : metric.baseline - value;
  return Math.max(0, Math.min(1, gain / range));
}

function stepPath(coordinates: Array<{ x: number; y: number }>) {
  if (!coordinates.length) return "";
  return coordinates.slice(1).reduce(
    (path, point) => `${path} H ${point.x.toFixed(2)} V ${point.y.toFixed(2)}`,
    `M ${coordinates[0].x.toFixed(2)} ${coordinates[0].y.toFixed(2)}`,
  );
}

function formatValue(value: number) {
  return Number.isInteger(value) ? String(value) : value.toFixed(value < 10 ? 2 : 1);
}

export function KpiChart({ series }: KpiChartProps) {
  const pointCount = Math.max(...series.map((metric) => metric.points.length), 0);
  const [hovered, setHovered] = useState(Math.max(0, pointCount - 1));
  const plotted = useMemo(() => series.map((metric) => ({
    metric,
    coordinates: metric.points.map((point, index) => {
      const x = pointCount <= 1
        ? WIDTH / 2
        : PAD_X + (index / (pointCount - 1)) * (WIDTH - PAD_X * 2);
      const normalized = improvement(metric, point.value);
      const y = HEIGHT - PAD_Y - normalized * (HEIGHT - PAD_Y * 2);
      return { x, y };
    }),
  })), [pointCount, series]);
  const activeX = pointCount <= 1
    ? WIDTH / 2
    : PAD_X + (hovered / (pointCount - 1)) * (WIDTH - PAD_X * 2);

  return (
    <div className="kpi-chart-wrap">
      <div className="chart-legend">
        {series.map((metric) => (
          <span key={metric.key}>
            <i className={`legend-series chart-accent-${metric.accent}`} />
            {metric.label}
            <strong>{formatValue(metric.best)} {metric.unit}</strong>
          </span>
        ))}
      </div>
      <svg
        className="kpi-chart"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label="KPI improvements over successive validated research steps"
        onPointerLeave={() => setHovered(Math.max(0, pointCount - 1))}
      >
        {[0, 1, 2, 3, 4].map((line) => {
          const y = PAD_Y + (line / 4) * (HEIGHT - PAD_Y * 2);
          return <line className="chart-grid-line" key={line} x1={PAD_X} y1={y} x2={WIDTH - PAD_X} y2={y} />;
        })}
        <text className="chart-scale-label" x={PAD_X} y={17}>100% of observed gain</text>
        <text className="chart-scale-label" x={PAD_X} y={HEIGHT - 8}>baseline</text>
        {plotted.map(({ metric, coordinates }) => (
          <g className={`chart-series chart-accent-${metric.accent}`} key={metric.key}>
            <path className="chart-series-halo" d={stepPath(coordinates)} />
            <path className="chart-main-line" d={stepPath(coordinates)} />
            {coordinates.map(({ x, y }, index) => (
              <g key={`${metric.key}-${metric.points[index].run}`}>
                <circle className="chart-point" cx={x} cy={y} r={hovered === index ? 4 : 2.8} />
              </g>
            ))}
          </g>
        ))}
        {Array.from({ length: pointCount }, (_, index) => {
          const x = pointCount <= 1
            ? WIDTH / 2
            : PAD_X + (index / (pointCount - 1)) * (WIDTH - PAD_X * 2);
          return (
            <rect
              className="chart-column-hit"
              key={index}
              x={x - (WIDTH - PAD_X * 2) / Math.max(pointCount - 1, 1) / 2}
              y={0}
              width={(WIDTH - PAD_X * 2) / Math.max(pointCount - 1, 1)}
              height={HEIGHT}
              tabIndex={0}
              onPointerEnter={() => setHovered(index)}
              onFocus={() => setHovered(index)}
              aria-label={series.map((metric) => {
                const point = metric.points[index];
                return point ? `${metric.label}: ${formatValue(point.value)} ${metric.unit}` : "";
              }).filter(Boolean).join(", ")}
            />
          );
        })}
        <line className="chart-active-line" x1={activeX} y1={PAD_Y} x2={activeX} y2={HEIGHT - PAD_Y} />
      </svg>
      <div className="chart-step-detail" aria-live="polite">
        <span className="chart-step-index">{String(hovered + 1).padStart(2, "0")}</span>
        <div>
          <strong>{series[0]?.points[hovered]?.label ?? "Research step"}</strong>
          <small>Validated research milestone</small>
        </div>
        <div className="chart-step-values">
          {series.map((metric) => {
            const point = metric.points[hovered];
            return point ? (
              <span key={metric.key}>
                <i className={`chart-accent-${metric.accent}`} />
                {formatValue(point.value)} <small>{metric.unit}</small>
              </span>
            ) : null;
          })}
        </div>
      </div>
      <div className="chart-axis-labels">
        <span>Baseline</span>
        <span>{pointCount} validated milestones</span>
        <span>Current best</span>
      </div>
    </div>
  );
}
