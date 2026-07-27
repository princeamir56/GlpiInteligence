import { Component, inject, signal, computed } from '@angular/core';
import { NgIf } from '@angular/common';
import { DashboardService } from '../../core/services/dashboard.service';
import { TechnicianRow } from '../../core/models/tabs.model';
import { DataTableComponent } from '../../shared/components/data-table/data-table.component';
import { ScatterChartComponent, ScatterPoint } from '../../shared/components/scatter-chart/scatter-chart.component';
import { BarChartComponent } from '../../shared/components/bar-chart/bar-chart.component';
import { SkeletonLoaderComponent } from '../../shared/components/skeleton-loader/skeleton-loader.component';
import { TabScaffoldComponent } from '../../shared/components/tab-scaffold/tab-scaffold.component';
import { TableColumn } from '../../shared/components/data-table/data-table.model';
import { topSeries, withRank } from '../../shared/tab-utils';

@Component({
  selector: 'app-techniciens',
  standalone: true,
  imports: [
    NgIf, DataTableComponent, ScatterChartComponent, BarChartComponent,
    SkeletonLoaderComponent, TabScaffoldComponent,
  ],
  templateUrl: './techniciens.component.html',
  styleUrl: './techniciens.component.css',
})
export class TechniciensComponent {
  private dash = inject(DashboardService);

  readonly loading = signal(true);
  readonly error = signal(false);
  readonly rows = signal<TechnicianRow[]>([]);

  readonly slaChart = computed(() => topSeries(this.rows(), 'name', 'sla_rate', 15, 'SLA %'));
  readonly scatter = computed<ScatterPoint[]>(() =>
    this.rows().map((r) => ({
      label: r.name,
      x: Number(r.total) || 0,
      y: Number(r.avg_resolution_days) || 0,
      sla: Number(r.sla_rate) || 0,
    })),
  );

  readonly columns: TableColumn[] = [
    { key: 'rank', label: '#', type: 'rank', width: '56px', align: 'center' },
    { key: 'name', label: 'Technicien', sortable: true },
    { key: 'total', label: 'Tickets', type: 'number', align: 'right', sortable: true },
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
    this.dash.tab<TechnicianRow[]>('/api/techniciens').subscribe({
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
