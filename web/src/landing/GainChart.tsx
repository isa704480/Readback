import { useEffect, useRef } from 'react';
import { useInView } from 'motion/react';
import {
  BarController,
  BarElement,
  CategoryScale,
  Chart,
  Legend,
  LinearScale,
  Tooltip,
} from 'chart.js';
import { useMotionAllowed } from '../lib/motion-prefs';

Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip, Legend);

/* The measured error budget, drawn to scale: how much recogniser error each
 * format absorbs with and without the constraint. Every value is a constant
 * passed in from Landing.tsx, which carries its source in docs/. The chart is
 * created when it scrolls into view, so the bars grow while someone is looking,
 * and is created without animation under reduced motion.
 *
 * The canvas is decoration of numbers the surrounding text already states;
 * its accessible name states them again for a screen reader. */

export interface GainSeries {
  label: string;
  unconstrained: number;
  constrained: number;
}

export interface GainChartProps {
  series: readonly GainSeries[];
  unconstrainedLabel: string;
  constrainedLabel: string;
  axisLabel: string;
  label: string;
  format: (value: number) => string;
}

function cssVar(name: string, fallback: string): string {
  try {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  } catch {
    return fallback;
  }
}

export default function GainChart({
  series,
  unconstrainedLabel,
  constrainedLabel,
  axisLabel,
  label,
  format,
}: GainChartProps) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const inView = useInView(box, { once: true, margin: '0px 0px -15% 0px' });
  const moving = useMotionAllowed();

  useEffect(() => {
    if (!inView || !canvas.current) return;
    const font = cssVar('--font-ui', 'system-ui, sans-serif');
    const muted = cssVar('--text-2', '#6e6e73');
    const grid = cssVar('--hairline', 'rgba(0,0,0,0.07)');

    const chart = new Chart(canvas.current, {
      type: 'bar',
      data: {
        labels: series.map((s) => s.label),
        datasets: [
          {
            label: unconstrainedLabel,
            data: series.map((s) => s.unconstrained),
            backgroundColor: cssVar('--text-4', '#aeaeb2'),
            borderRadius: 6,
            maxBarThickness: 56,
          },
          {
            label: constrainedLabel,
            data: series.map((s) => s.constrained),
            backgroundColor: cssVar('--accent', '#0071e3'),
            borderRadius: 6,
            maxBarThickness: 56,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: moving ? { duration: 1100, easing: 'easeOutQuart' } : false,
        interaction: { mode: 'index', intersect: false },
        font: { family: font },
        plugins: {
          legend: {
            position: 'bottom',
            labels: { color: muted, font: { family: font, size: 13 }, boxWidth: 12, boxHeight: 12 },
          },
          tooltip: {
            callbacks: { label: (ctx) => `${ctx.dataset.label}: ${format(Number(ctx.raw))}` },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { color: muted, font: { family: cssVar('--font-mono', 'monospace'), size: 13 } },
          },
          y: {
            beginAtZero: true,
            grid: { color: grid },
            border: { display: false },
            title: { display: true, text: axisLabel, color: muted, font: { family: font, size: 12 } },
            ticks: { color: muted, font: { family: font, size: 12 }, callback: (v) => format(Number(v)) },
          },
        },
      },
    });
    return () => chart.destroy();
  }, [inView, moving, series, unconstrainedLabel, constrainedLabel, axisLabel, format]);

  return (
    <div ref={box} className="chart">
      <canvas ref={canvas} role="img" aria-label={label} />
    </div>
  );
}
