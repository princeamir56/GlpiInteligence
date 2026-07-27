import { Component, Input, effect, inject, signal, computed } from '@angular/core';
import { NgIf, DecimalPipe } from '@angular/common';
import { NgChartsModule } from 'ng2-charts';
import { ChartConfiguration } from 'chart.js';
import { ChartSeries } from '../../../core/models/common.model';
import { ThemeService } from '../../../core/services/theme.service';
import { readChartTheme } from '../chart-theme';

/** Donut chart with a total rendered in the center hole. */
@Component({
  selector: 'app-donut-chart',
  standalone: true,
  imports: [NgIf, DecimalPipe, NgChartsModule],
  templateUrl: './donut-chart.component.html',
  styleUrl: './donut-chart.component.css',
})
export class DonutChartComponent {
  private theme = inject(ThemeService);

  private _data = signal<ChartSeries | null>(null);
  @Input() set data(value: ChartSeries | null) {
    this._data.set(value);
  }
  @Input() centerLabel = 'Total';

  readonly config = signal<ChartConfiguration<'doughnut'> | null>(null);
  readonly total = computed(() => (this._data()?.values ?? []).reduce((a, b) => a + b, 0));

  constructor() {
    effect(
      () => {
        this.theme.resolved();
        const data = this._data();
        this.config.set(data ? this.build(data) : null);
      },
      { allowSignalWrites: true },
    );
  }

  get hasData(): boolean {
    return (this._data()?.values?.length ?? 0) > 0;
  }

  private build(d: ChartSeries): ChartConfiguration<'doughnut'> {
    const t = readChartTheme();
    return {
      type: 'doughnut',
      data: {
        labels: d.labels,
        datasets: [
          {
            data: d.values,
            backgroundColor: d.values.map((_, i) => t.categorical[i % t.categorical.length]),
            borderColor: t.surface,
            borderWidth: 3,
            hoverOffset: 6,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '68%',
        animation: { duration: 700, easing: 'easeOutQuart' },
        plugins: {
          legend: {
            position: 'right',
            labels: { color: t.muted, usePointStyle: true, boxWidth: 8, padding: 12, font: { size: 12 } },
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
      },
    };
  }
}
