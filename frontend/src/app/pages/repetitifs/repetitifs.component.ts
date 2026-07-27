import { Component, inject, signal, computed } from '@angular/core';
import { NgIf, NgFor } from '@angular/common';
import { LucideAngularModule } from 'lucide-angular';
import { DashboardService } from '../../core/services/dashboard.service';
import { RepetitiveRow } from '../../core/models/tabs.model';
import { DataTableComponent } from '../../shared/components/data-table/data-table.component';
import { BarChartComponent } from '../../shared/components/bar-chart/bar-chart.component';
import { SkeletonLoaderComponent } from '../../shared/components/skeleton-loader/skeleton-loader.component';
import { TabScaffoldComponent } from '../../shared/components/tab-scaffold/tab-scaffold.component';
import { StaggerDirective } from '../../shared/directives/stagger.directive';
import { TableColumn } from '../../shared/components/data-table/data-table.model';
import { topSeries, withRank } from '../../shared/tab-utils';

@Component({
  selector: 'app-repetitifs',
  standalone: true,
  imports: [
    NgIf, NgFor, LucideAngularModule, DataTableComponent, BarChartComponent,
    SkeletonLoaderComponent, TabScaffoldComponent, StaggerDirective,
  ],
  templateUrl: './repetitifs.component.html',
  styleUrl: './repetitifs.component.css',
})
export class RepetitifsComponent {
  private dash = inject(DashboardService);

  readonly loading = signal(true);
  readonly error = signal(false);
  readonly rows = signal<RepetitiveRow[]>([]);

  readonly barChart = computed(() => topSeries(this.rows(), 'title', 'count', 12, 'Occurrences'));
  readonly topClusters = computed(() => this.rows().slice(0, 6));

  readonly columns: TableColumn[] = [
    { key: 'rank', label: '#', type: 'rank', width: '56px', align: 'center' },
    { key: 'title', label: 'Cluster', sortable: true },
    { key: 'category', label: 'Catégorie', sortable: true },
    { key: 'count', label: 'Occurrences', type: 'number', align: 'right', sortable: true },
    {
      key: 'keywords',
      label: 'Mots-clés',
      sortable: false,
      format: (v) => (Array.isArray(v) ? (v as string[]).join(', ') : String(v ?? '—')),
    },
  ];

  constructor() {
    this.load();
  }

  keywords(c: RepetitiveRow): string[] {
    return Array.isArray(c.keywords) ? c.keywords.slice(0, 6) : [];
  }
  samples(c: RepetitiveRow): string[] {
    return Array.isArray(c.sample_titles) ? c.sample_titles.slice(0, 3) : [];
  }

  load(): void {
    this.loading.set(true);
    this.error.set(false);
    this.dash.tab<RepetitiveRow[]>('/api/repetitifs').subscribe({
      next: (res) => {
        this.rows.set(withRank(res ?? [], 'count'));
        this.loading.set(false);
      },
      error: () => {
        this.error.set(true);
        this.loading.set(false);
      },
    });
  }
}
