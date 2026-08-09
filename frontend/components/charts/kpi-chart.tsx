"use client";

import { useId, useMemo, useState } from "react";
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

function stepAreaPath(coordinates: Array<{ x: number; y: number }>, baselineY: number) {
  if (!coordinates.length) return "";
  const first = coordinates[0];
  return `${stepPath(coordinates)} V ${baselineY.toFixed(2)} H ${first.x.toFixed(2)} Z`;
}

function scaleRun(run: number, minRun: number, maxRun: number) {
  if (maxRun === minRun) return WIDTH / 2;
  return PAD_X + ((run - minRun) / (maxRun - minRun)) * (WIDTH - PAD_X * 2);
}

function formatValue(value: number) {
  return Number.isInteger(value) ? String(value) : value.toFixed(value < 10 ? 2 : 1);
}

export function KpiChart({ series }: KpiChartProps) {
  const chartId = useId().replace(/:/g, "");
  const { plotted, timeline } = useMemo(() => {
    const runs = series.flatMap((metric) => metric.points.map((point) => point.run));
    const minRun = runs.length ? Math.min(...runs) : 0;
    const maxRun = runs.length ? Math.max(...runs) : 0;
    const plottedSeries = series.map((metric, seriesIndex) => ({
      metric,
      seriesIndex,
      coordinates: metric.points.map((point) => {
        const x = scaleRun(point.run, minRun, maxRun);
        const normalized = improvement(metric, point.value);
        const y = HEIGHT - PAD_Y - normalized * (HEIGHT - PAD_Y * 2);
        return { x, y };
      }),
    }));
    const timelineRuns = Array.from(new Set(runs)).sort((a, b) => a - b);
    const timelinePoints = timelineRuns.map((run) => ({
      run,
      x: scaleRun(run, minRun, maxRun),
      label: series
        .flatMap((metric) => metric.points)
        .find((point) => point.run === run)?.label ?? "Research milestone",
    }));
    return { plotted: plottedSeries, timeline: timelinePoints };
  }, [series]);
  const [hovered, setHovered] = useState(Math.max(0, timeline.length - 1));
  const activeIndex = Math.min(hovered, Math.max(0, timeline.length - 1));
  const activeMilestone = timeline[activeIndex];
  const activeRun = activeMilestone?.run;
  const activeX = activeMilestone?.x ?? WIDTH / 2;
  const activePoints = series.map((metric) => metric.points.reduce<MetricSeries["points"][number] | undefined>(
    (latest, point) => activeRun !== undefined && point.run <= activeRun ? point : latest,
    undefined,
  ));

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
        onPointerLeave={() => setHovered(Math.max(0, timeline.length - 1))}
      >
        <defs>
          <linearGradient id={`${chartId}-dither-fade`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="white" stopOpacity="0.9" />
            <stop offset="0.68" stopColor="white" stopOpacity="0.34" />
            <stop offset="1" stopColor="white" stopOpacity="0.15" />
          </linearGradient>
          <mask id={`${chartId}-dither-mask`}>
            <rect width={WIDTH} height={HEIGHT} fill={`url(#${chartId}-dither-fade)`} />
          </mask>
          {series.map((metric, seriesIndex) => (
            <pattern
              className={`chart-dither-pattern chart-accent-${metric.accent}`}
              id={`${chartId}-dither-${seriesIndex}`}
              key={metric.key}
              width="7"
              height="7"
              patternUnits="userSpaceOnUse"
            >
              <circle cx="1.25" cy="1.25" r="0.82" fill="currentColor" />
              <circle cx="4.75" cy="4.75" r="0.46" fill="currentColor" />
            </pattern>
          ))}
        </defs>
        {[0, 1, 2, 3, 4].map((line) => {
          const y = PAD_Y + (line / 4) * (HEIGHT - PAD_Y * 2);
          return <line className="chart-grid-line" key={line} x1={PAD_X} y1={y} x2={WIDTH - PAD_X} y2={y} />;
        })}
        <text className="chart-scale-label" x={PAD_X} y={17}>100% of observed gain</text>
        <text className="chart-scale-label" x={PAD_X} y={HEIGHT - 8}>baseline</text>
        {plotted.map(({ metric, seriesIndex, coordinates }) => (
          <g className={`chart-series chart-accent-${metric.accent}`} key={metric.key}>
            <path
              className="chart-dither-area"
              d={stepAreaPath(coordinates, HEIGHT - PAD_Y)}
              fill={`url(#${chartId}-dither-${seriesIndex})`}
              mask={`url(#${chartId}-dither-mask)`}
            />
            <path className="chart-series-halo" d={stepPath(coordinates)} />
            <path className="chart-main-line" d={stepPath(coordinates)} />
            {coordinates.map(({ x, y }, index) => (
              <g key={`${metric.key}-${metric.points[index].run}`}>
                <circle className="chart-point" cx={x} cy={y} r={activeRun === metric.points[index].run ? 4 : 2.8} />
              </g>
            ))}
          </g>
        ))}
        {timeline.map(({ x }, index) => {
          const previousX = timeline[index - 1]?.x;
          const nextX = timeline[index + 1]?.x;
          const left = previousX === undefined ? PAD_X : (previousX + x) / 2;
          const right = nextX === undefined ? WIDTH - PAD_X : (x + nextX) / 2;
          return (
            <rect
              className="chart-column-hit"
              key={index}
              x={left}
              y={0}
              width={Math.max(1, right - left)}
              height={HEIGHT}
              tabIndex={0}
              onPointerEnter={() => setHovered(index)}
              onFocus={() => setHovered(index)}
              aria-label={series.map((metric) => {
                const point = metric.points.reduce<MetricSeries["points"][number] | undefined>(
                  (latest, candidate) => candidate.run <= timeline[index].run ? candidate : latest,
                  undefined,
                );
                return point ? `${metric.label}: ${formatValue(point.value)} ${metric.unit}` : "";
              }).filter(Boolean).join(", ")}
            />
          );
        })}
        <line className="chart-active-line" x1={activeX} y1={PAD_Y} x2={activeX} y2={HEIGHT - PAD_Y} />
      </svg>
      <div className="chart-step-detail" aria-live="polite">
        <span className="chart-step-index">{String(activeIndex + 1).padStart(2, "0")}</span>
        <div>
          <strong>{activeMilestone?.label ?? "Research step"}</strong>
          <small>Validated research milestone</small>
        </div>
        <div className="chart-step-values">
          {series.map((metric, index) => {
            const point = activePoints[index];
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
        <span>{timeline.length} validated milestones</span>
        <span>Current best</span>
      </div>
    </div>
  );
}
