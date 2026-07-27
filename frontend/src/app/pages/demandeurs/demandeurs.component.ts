import { Component, inject, signal, computed } from '@angular/core';
import { NgIf } from '@angular/common';
import { DashboardService } from '../../core/services/dashboard.service';
import { Demandeur } from '../../core/models/tabs.model';
import { DataTableComponent } from '../../shared/components/data-table/data-table.component';
import { BarChartComponent } from '../../shared/components/bar-chart/bar-chart.component';
import { SkeletonLoaderComponent } from '../../shared/components/skeleton-loader/skeleton-loader.component';
import { TabScaffoldComponent } from '../../shared/components/tab-scaffold/tab-scaffold.component';
import { TableColumn } from '../../shared/components/data-table/data-table.model';
import { topSeries, stackedSeries, withRank, profileTone } from '../../shared/tab-utils';

@Component({
  selector: 'app-demandeurs',
  standalone: true,
  imports: [
    NgIf, DataTableComponent, BarChartComponent, SkeletonLoaderComponent, TabScaffoldComponent,
  ],
  templateUrl: './demandeurs.component.html',
  styleUrl: './demandeurs.component.css',
})
export class DemandeursComponent {
  private dash = inject(DashboardService);

  readonly loading = signal(true);
  readonly error = signal(false);
  readonly rows = signal<Demandeur[]>([]);

  readonly topChart = computed(() => topSeries(this.rows(), 'name', 'total', 15, 'Tickets'));
  readonly stackedChart = computed(() =>
    stackedSeries(
      this.rows(),
      'name',
      [
        { key: 'incidents', label: 'Incidents' },
        { key: 'requests', label: 'Demandes' },
      ],
      'total',
      15,
    ),
  );

  readonly columns: TableColumn[] = [
    { key: 'rank', label: '#', type: 'rank', width: '56px', align: 'center' },
    { key: 'name', label: 'Demandeur', sortable: true },
    { key: 'total', label: 'Total', type: 'number', align: 'right', sortable: true },
    { key: 'incidents', label: 'Incidents', type: 'number', align: 'right', sortable: true },
    { key: 'requests', label: 'Demandes', type: 'number', align: 'right', sortable: true },
    { key: 'open', label: 'Ouverts', type: 'number', align: 'right', sortable: true },
    { key: 'repetitive', label: 'Répétitifs', type: 'number', align: 'right', sortable: true },
    { key: 'high_priority', label: 'Prio. haute', type: 'number', align: 'right', sortable: true },
    {
      key: 'tickets_per_month',
      label: 'Tickets/mois',
      type: 'number',
      align: 'right',
      sortable: true,
    },
    {
      key: 'profile',
      label: 'Profil',
      type: 'badge',
      badgeTone: (r) => profileTone(String((r as { profile?: string }).profile)),
    },
  ];

  constructor() {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.error.set(false);
    this.dash.tab<Demandeur[]>('/api/demandeurs').subscribe({
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
