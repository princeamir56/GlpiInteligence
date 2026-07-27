import { Component, Input, effect, inject, signal } from '@angular/core';
import { NgIf } from '@angular/common';
import { NgChartsModule } from 'ng2-charts';
import { ChartConfiguration } from 'chart.js';
import { ChartSeries, StackedChartData } from '../../../core/models/common.model';
import { ThemeService } from '../../../core/services/theme.service';
import { readChartTheme, withAlpha } from '../chart-theme';

/** Vertical bar chart. Accepts a single ChartSeries or a StackedChartData. */
@Component({
  selector: 'app-bar-chart',
  standalone: true,
  imports: [NgIf, NgChartsModule],
  templateUrl: './bar-chart.component.html',
  styleUrl: './bar-chart.component.css',
})
export class BarChartComponent {
  private theme = inject(ThemeService);

  private _data = signal<ChartSeries | StackedChartData | null>(null);
  @Input() set data(value: ChartSeries | StackedChartData | null) {
    this._data.set(value);
  }
  @Input() horizontal = false;

  readonly config = signal<ChartConfiguration<'bar'> | null>(null);

  constructor() {
    effect(
      () => {
        // Re-read theme colors whenever the resolved theme or data changes.
        this.theme.resolved();
        const data = this._data();
        this.config.set(data ? this.build(data) : null);
      },
      { allowSignalWrites: true },
    );
  }

  get hasData(): boolean {
    const d = this._data();
    if (!d) return false;
    return 'values' in d ? d.values.length > 0 : d.series.length > 0;
  }

  private isStacked(d: ChartSeries | StackedChartData): d is StackedChartData {
    return 'series' in d;
  }

  private build(d: ChartSeries | StackedChartData): ChartConfiguration<'bar'> {
    const t = readChartTheme();
    const datasets = this.isStacked(d)
      ? d.series.map((s, i) => ({
          label: s.label,
          data: s.values,
          backgroundColor: s.color ?? t.categorical[i % t.categorical.length],
          borderRadius: 6,
          maxBarThickness: 46,
        }))
      : [
          {
            label: d.label ?? '',
            data: d.values,
            backgroundColor: d.values.map((_, i) =>
              withAlpha(t.categorical[i % t.categorical.length], 0.85),
            ),
            borderRadius: 6,
            maxBarThickness: 46,
          },
        ];

    return {
      type: 'bar',
      data: { labels: d.labels, datasets },
      options: {
        indexAxis: this.horizontal ? 'y' : 'x',
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 700, easing: 'easeOutQuart' },
        plugins: {
          legend: {
            display: this.isStacked(d),
            labels: { color: t.muted, usePointStyle: true, boxWidth: 8, font: { size: 12 } },
          },
          tooltip: {
            backgroundColor: t.surface,
            titleColor: t.text,
            bodyColor: t.text,
            borderColor: t.grid,
            borderWidth: 1,
            padding: 10,
            cornerRadius: 8,
          },
        },
        scales: {
          x: {
            stacked: this.isStacked(d),
            grid: { display: this.horizontal, color: t.grid },
            ticks: { color: t.muted, font: { size: 11 } },
            border: { display: false },
          },
          y: {
            stacked: this.isStacked(d),
            grid: { display: !this.horizontal, color: t.grid },
            ticks: { color: t.muted, font: { size: 11 } },
            border: { display: false },
          },
        },
      },
    };
  }
}
