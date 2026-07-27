import { Component, inject, signal, computed } from '@angular/core';
import { NgIf } from '@angular/common';
import { DashboardService } from '../../core/services/dashboard.service';
import { SiteRow } from '../../core/models/tabs.model';
import { DataTableComponent } from '../../shared/components/data-table/data-table.component';
import { BarChartComponent } from '../../shared/components/bar-chart/bar-chart.component';
import { SkeletonLoaderComponent } from '../../shared/components/skeleton-loader/skeleton-loader.component';
import { TabScaffoldComponent } from '../../shared/components/tab-scaffold/tab-scaffold.component';
import { TableColumn } from '../../shared/components/data-table/data-table.model';
import { topSeries, withRank } from '../../shared/tab-utils';

@Component({
  selector: 'app-sites',
  standalone: true,
  imports: [
    NgIf, DataTableComponent, BarChartComponent, SkeletonLoaderComponent, TabScaffoldComponent,
  ],
  templateUrl: './sites.component.html',
  styleUrl: './sites.component.css',
})
export class SitesComponent {
  private dash = inject(DashboardService);

  readonly loading = signal(true);
  readonly error = signal(false);
  readonly rows = signal<SiteRow[]>([]);

  readonly barChart = computed(() => topSeries(this.rows(), 'name', 'total', 15, 'Tickets'));

  readonly columns: TableColumn[] = [
    { key: 'rank', label: '#', type: 'rank', width: '56px', align: 'center' },
    { key: 'name', label: 'Site', sortable: true },
    { key: 'total', label: 'Total', type: 'number', align: 'right', sortable: true },
    { key: 'open', label: 'Ouverts', type: 'number', align: 'right', sortable: true },
    { key: 'avg_resolution_days', label: 'Résol. moy. (j)', type: 'number', align: 'right', sortable: true },
    { key: 'sla_rate', label: 'SLA', type: 'sla', sortable: true, width: '150px' },
  ];

  constructor() {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.error.set(false);
    this.dash.tab<SiteRow[]>('/api/sites').subscribe({
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
