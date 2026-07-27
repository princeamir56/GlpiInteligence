import { Component, inject, signal, computed } from '@angular/core';
import { NgFor, NgIf } from '@angular/common';
import { LucideAngularModule } from 'lucide-angular';
import { DashboardService } from '../../core/services/dashboard.service';
import { NotificationService } from '../../core/services/notification.service';
import { Overview, OverviewAlert, Kpi } from '../../core/models/overview.model';
import { KpiCardComponent } from '../../shared/components/kpi-card/kpi-card.component';
import { BarChartComponent } from '../../shared/components/bar-chart/bar-chart.component';
import { HorizBarChartComponent } from '../../shared/components/horiz-bar-chart/horiz-bar-chart.component';
import { DonutChartComponent } from '../../shared/components/donut-chart/donut-chart.component';
import { AlertsPanelComponent } from '../../shared/components/alerts-panel/alerts-panel.component';
import { SkeletonLoaderComponent } from '../../shared/components/skeleton-loader/skeleton-loader.component';
import { StaggerDirective } from '../../shared/directives/stagger.directive';
import { fadeUp } from '../../shared/animations';

/** KPI icon + "up is good?" mapping keyed by common KPI keys/labels. */
const KPI_META: Record<string, { icon: string; upIsGood: boolean; unit?: string; decimals?: number }> = {
  total: { icon: 'inbox', upIsGood: true },
  tickets: { icon: 'inbox', upIsGood: true },
  incidents: { icon: 'alert-triangle', upIsGood: false },
  requests: { icon: 'repeat', upIsGood: true },
  open: { icon: 'loader', upIsGood: false },
  resolved: { icon: 'check-check', upIsGood: true },
  sla: { icon: 'check', upIsGood: true, unit: '%' },
  mttr: { icon: 'loader', upIsGood: false, unit: ' j', decimals: 1 },
  backlog: { icon: 'inbox', upIsGood: false },
};

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [
    NgFor, NgIf, LucideAngularModule, KpiCardComponent, BarChartComponent,
    HorizBarChartComponent, DonutChartComponent, AlertsPanelComponent,
    SkeletonLoaderComponent, StaggerDirective,
  ],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.css',
  animations: [fadeUp],
})
export class DashboardComponent {
  private dash = inject(DashboardService);
  private notif = inject(NotificationService);

  readonly loading = signal(true);
  readonly error = signal(false);
  readonly data = signal<Overview | null>(null);

  readonly kpis = computed(() => this.data()?.kpis ?? []);
  readonly alerts = signal<OverviewAlert[]>([]);

  constructor() {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.error.set(false);
    this.dash.overview().subscribe({
      next: (res) => {
        this.data.set(res);
        this.alerts.set(res.alerts ?? []);
        this.loading.set(false);
      },
      error: () => {
        this.error.set(true);
        this.loading.set(false);
      },
    });
  }

  meta(kpi: Kpi) {
    const k = (kpi.key || kpi.label || '').toLowerCase();
    const hit = Object.keys(KPI_META).find((m) => k.includes(m));
    return hit ? KPI_META[hit] : { icon: 'layout-dashboard', upIsGood: true, unit: undefined, decimals: undefined };
  }

  ack(alert: OverviewAlert): void {
    this.dash.acknowledgeRecommendation(alert.id).subscribe({
      next: () => {
        this.alerts.update((list) =>
          list.map((a) => (a.id === alert.id ? { ...a, acknowledged: true } : a)),
        );
        this.notif.toast('Alerte acquittée', 'success', 4000);
      },
    });
  }
}
