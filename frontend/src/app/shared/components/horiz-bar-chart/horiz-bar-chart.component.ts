import { Component, Input } from '@angular/core';
import { BarChartComponent } from '../bar-chart/bar-chart.component';
import { ChartSeries, StackedChartData } from '../../../core/models/common.model';

/** Horizontal bar chart — a thin preset over BarChartComponent. */
@Component({
  selector: 'app-horiz-bar-chart',
  standalone: true,
  imports: [BarChartComponent],
  templateUrl: './horiz-bar-chart.component.html',
  styleUrl: './horiz-bar-chart.component.css',
})
export class HorizBarChartComponent {
  @Input() data: ChartSeries | StackedChartData | null = null;
}
