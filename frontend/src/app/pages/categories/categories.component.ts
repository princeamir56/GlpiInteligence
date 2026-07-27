import { Component, inject, signal, computed } from '@angular/core';
import { NgIf } from '@angular/common';
import { DashboardService } from '../../core/services/dashboard.service';
import { CategoryRow } from '../../core/models/tabs.model';
import { DataTableComponent } from '../../shared/components/data-table/data-table.component';
import { DonutChartComponent } from '../../shared/components/donut-chart/donut-chart.component';
import { BarChartComponent } from '../../shared/components/bar-chart/bar-chart.component';
import { SkeletonLoaderComponent } from '../../shared/components/skeleton-loader/skeleton-loader.component';
import { TabScaffoldComponent } from '../../shared/components/tab-scaffold/tab-scaffold.component';
import { TableColumn } from '../../shared/components/data-table/data-table.model';
import { topSeries, stackedSeries, withRank } from '../../shared/tab-utils';

@Component({
  selector: 'app-categories',
  standalone: true,
  imports: [
    NgIf, DataTableComponent, DonutChartComponent, BarChartComponent,
    SkeletonLoaderComponent, TabScaffoldComponent,
  ],
  templateUrl: './categories.component.html',
  styleUrl: './categories.component.css',
})
export class CategoriesComponent {
  private dash = inject(DashboardService);

  readonly loading = signal(true);
  readonly error = signal(false);
  readonly rows = signal<CategoryRow[]>([]);

  readonly donutChart = computed(() => topSeries(this.rows(), 'name', 'total', 8, 'Tickets'));
  readonly stackedChart = computed(() =>
    stackedSeries(
      this.rows(),
      'name',
      [
        { key: 'incidents', label: 'Incidents' },
        { key: 'requests', label: 'Demandes' },
      ],
      'total',
      12,
    ),
  );

  readonly columns: TableColumn[] = [
    { key: 'rank', label: '#', type: 'rank', width: '56px', align: 'center' },
    { key: 'name', label: 'Catégorie', sortable: true },
    { key: 'total', label: 'Total', type: 'number', align: 'right', sortable: true },
    { key: 'incidents', label: 'Incidents', type: 'number', align: 'right', sortable: true },
    { key: 'requests', label: 'Demandes', type: 'number', align: 'right', sortable: true },
    { key: 'open', label: 'Ouverts', type: 'number', align: 'right', sortable: true },
    { key: 'sla_rate', label: 'SLA', type: 'sla', sortable: true, width: '150px' },
  ];

  constructor() {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.error.set(false);
    this.dash.tab<CategoryRow[]>('/api/categories').subscribe({
      next: (res) => {
        this.rows.set(withRank(res ?? [], 'total'));
        this.loading.set(false);
      },
      error: () => {
        this.error.set(true);
        this.loading.set(false);
      },
    });
  }
}
