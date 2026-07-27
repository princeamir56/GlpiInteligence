import { Component, Input, effect, inject, signal } from '@angular/core';
import { NgIf } from '@angular/common';
import { NgChartsModule } from 'ng2-charts';
import { ChartConfiguration } from 'chart.js';
import { ThemeService } from '../../../core/services/theme.service';
import { readChartTheme, withAlpha } from '../chart-theme';

export interface ScatterPoint {
  label: string;
  x: number; // ticket count
  y: number; // avg resolution days
  sla: number; // 0-100, drives dot color
}

/** Bubble/scatter plot: X=tickets, Y=avg resolution days, color=SLA%. */
@Component({
  selector: 'app-scatter-chart',
  standalone: true,
  imports: [NgIf, NgChartsModule],
  templateUrl: './scatter-chart.component.html',
  styleUrl: './scatter-chart.component.css',
})
export class ScatterChartComponent {
  private theme = inject(ThemeService);

  private _points = signal<ScatterPoint[]>([]);
  @Input() set points(value: ScatterPoint[] | null) {
    this._points.set(value ?? []);
  }
  @Input() xLabel = 'Tickets traités';
  @Input() yLabel = 'Résolution moy. (jours)';

  readonly config = signal<ChartConfiguration<'scatter'> | null>(null);

  constructor() {
    effect(
      () => {
        this.theme.resolved();
        const pts = this._points();
        this.config.set(pts.length ? this.build(pts) : null);
      },
      { allowSignalWrites: true },
    );
  }

  get hasData(): boolean {
    return this._points().length > 0;
  }

  private slaColor(sla: number): string {
    return sla >= 90
      ? cssv('--success', '#10b981')
      : sla >= 70
        ? cssv('--warning', '#f59e0b')
        : cssv('--danger', '#ef4444');
  }

  private build(points: ScatterPoint[]): ChartConfiguration<'scatter'> {
    const t = readChartTheme();
    return {
      type: 'scatter',
      data: {
        datasets: points.map((p) => ({
          label: p.label,
          data: [{ x: p.x, y: p.y }],
          backgroundColor: withAlpha(this.slaColor(p.sla), 0.75),
          borderColor: this.slaColor(p.sla),
          borderWidth: 1.5,
          pointRadius: 7,
          pointHoverRadius: 10,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 700, easing: 'easeOutQuart' },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: t.surface,
            titleColor: t.text,
            bodyColor: t.text,
            borderColor: t.grid,
            borderWidth: 1,
            padding: 10,
            cornerRadius: 8,
            callbacks: {
              title: (items) => items[0]?.dataset.label ?? '',
              label: (ctx) => {
                const p = points[ctx.datasetIndex];
                return `${this.xLabel}: ${p.x} · ${this.yLabel}: ${p.y} · SLA: ${p.sla}%`;
              },
            },
          },
        },
        scales: {
          x: {
            title: { display: true, text: this.xLabel, color: t.muted, font: { size: 11 } },
            grid: { color: t.grid },
            ticks: { color: t.muted, font: { size: 11 } },
            border: { display: false },
          },
          y: {
            title: { display: true, text: this.yLabel, color: t.muted, font: { size: 11 } },
            grid: { color: t.grid },
            ticks: { color: t.muted, font: { size: 11 } },
            border: { display: false },
          },
        },
      },
    };
  }
}

function cssv(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}
