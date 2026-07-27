import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';
import { ApiService } from './api.service';
import { Overview } from '../models/overview.model';
import { ChartSeries, TabQuery } from '../models/common.model';

type BackendNamedCount = { id: number; name: string; count: number };
type BackendTechSla = { technician_id: number; name: string; sla_pct: number; total: number };

interface BackendOverview {
  kpis: {
    total_tickets: number;
    resolved_pct: number;
    sla_global_pct: number;
    repetitive_count: number;
    active_sites_count: number;
    top_category?: string | null;
  };
  charts: {
    top_sites: BackendNamedCount[];
    top_categories: BackendNamedCount[];
    top_requesters: BackendNamedCount[];
    sla_by_technician: BackendTechSla[];
  };
  alerts: {
    recommendation_id: string;
    severity: string;
    type?: string;
    title: string;
    description: string;
    created_at?: string;
  }[];
}

function toSeries(rows: BackendNamedCount[], label: string): ChartSeries {
  return {
    labels: (rows ?? []).map((r) => r.name),
    values: (rows ?? []).map((r) => r.count),
    label,
  };
}

function toOverview(b: BackendOverview): Overview {
  return {
    kpis: [
      { key: 'total_tickets', label: 'Total tickets', value: b.kpis.total_tickets },
      { key: 'resolved_pct', label: 'Résolus', value: b.kpis.resolved_pct, unit: '%' },
      { key: 'sla_global_pct', label: 'SLA global', value: b.kpis.sla_global_pct, unit: '%' },
      { key: 'repetitive_count', label: 'Tickets répétitifs', value: b.kpis.repetitive_count },
      { key: 'active_sites_count', label: 'Sites actifs', value: b.kpis.active_sites_count },
      { key: 'top_category', label: 'Top catégorie', value: 0, unit: b.kpis.top_category ?? '—' } as any,
    ],
    charts: {
      top_sites: toSeries(b.charts.top_sites, 'Tickets'),
      top_categories: toSeries(b.charts.top_categories, 'Tickets'),
      top_requesters: toSeries(b.charts.top_requesters, 'Tickets'),
      sla_per_technician: {
        labels: (b.charts.sla_by_technician ?? []).map((r) => r.name),
        values: (b.charts.sla_by_technician ?? []).map((r) => r.sla_pct),
        label: 'SLA %',
      },
    },
    alerts: (b.alerts ?? []).map((a) => ({
      id: a.recommendation_id,
      severity: a.severity,
      title: a.title,
      description: a.description,
    })),
  };
}

/** Backend wraps every tab in `{ items: [...] }` and uses different field
 * names than the frontend models. Unwrap and remap per path. */
function remapTab(path: string, res: any): any[] {
  const items: any[] = Array.isArray(res) ? res : Array.isArray(res?.items) ? res.items : [];
  switch (true) {
    case path.includes('/api/demandeurs'):
      return items;
    case path.includes('/api/services'):
      return items.map((r) => ({
        name: r.service ?? r.name ?? `Service #${r.service_id ?? ''}`,
        total: r.total,
        incidents: r.incidents ?? 0,
        requests: r.requests ?? 0,
        open: r.open,
        high_priority: r.high_priority,
        criticality: r.criticality,
        sla_rate: r.sla_pct ?? 0,
        avg_resolution_days: r.avg_resolution_days,
      }));
    case path.includes('/api/sites'):
      return items.map((r) => ({
        name: r.name,
        total: r.total,
        open: r.open,
        resolved: r.resolved,
        part_pct: r.part_pct,
        sla_rate: r.sla_pct ?? 0,
        avg_resolution_days: r.avg_resolution_days,
      }));
    case path.includes('/api/repetitifs'):
      return items.map((r, i) => ({
        cluster_id: r.cluster_id,
        title: (r.sample_titles && r.sample_titles[0]) || `Cluster #${r.cluster_id ?? i + 1}`,
        count: r.ticket_count ?? 0,
        keywords: r.top_keywords ?? [],
        sample_titles: r.sample_titles ?? [],
        category: r.severity,
      }));
    case path.includes('/api/techniciens'):
      return items.map((r) => ({
        name: r.name,
        total: r.total,
        open: (r.total ?? 0) - (r.resolved ?? 0),
        avg_resolution_days: r.avg_resolution_days,
        sla_rate: r.sla_pct,
      }));
    case path.includes('/api/categories'):
      return items.map((r) => ({
        name: r.name,
        total: r.total,
        incidents: r.incidents ?? 0,
        requests: r.requests ?? 0,
        open: r.open ?? (r.total ?? 0) - (r.resolved ?? 0),
        sla_rate: r.sla_pct ?? r.resolution_rate ?? 0,
        avg_resolution_days: r.avg_resolution_days,
      }));
    default:
      return items;
  }
}

/**
 * Calls the analytics endpoints. Each tab endpoint returns an arbitrary row
 * shape, so tabs type the response themselves via the generic helpers.
 */
@Injectable({ providedIn: 'root' })
export class DashboardService {
  private api = inject(ApiService);

  overview(query?: TabQuery): Observable<Overview> {
    return this.api
      .get<BackendOverview>('/api/overview', query as Record<string, unknown>)
      .pipe(map(toOverview));
  }

  tab<T>(path: string, query?: TabQuery): Observable<T> {
    return this.api
      .get<any>(path, query as Record<string, unknown>)
      .pipe(map((res) => remapTab(path, res) as unknown as T));
  }

  acknowledgeRecommendation(id: string): Observable<unknown> {
    return this.api.post(`/api/recommendations/${id}/acknowledge`);
  }

  recommendations<T>(): Observable<T> {
    return this.api.get<T>('/api/recommendations');
  }

  predictionsVolume<T>(query?: TabQuery): Observable<T> {
    return this.api.get<T>('/api/predictions/volume', query as Record<string, unknown>);
  }

  predictionsSlaRisk<T>(query?: TabQuery): Observable<T> {
    return this.api.get<T>('/api/predictions/sla_risk', query as Record<string, unknown>);
  }
}
