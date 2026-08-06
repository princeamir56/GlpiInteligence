import { ChartSeries } from './common.model';

export interface Kpi {
  key: string;
  label: string;
  value: number;
  unit?: string;
  /** When set, renders as plain text instead of the animated numeric value (e.g. a category name). */
  text?: string;
  delta?: number; // percentage change vs previous period
  trend?: 'up' | 'down' | 'flat';
}

export interface OverviewAlert {
  id: string;
  severity: string; // CRITIQUE / ELEVE / ...
  title: string;
  description: string;
  acknowledged?: boolean;
}

export interface Overview {
  kpis: Kpi[];
  charts: {
    top_sites: ChartSeries;
    top_categories: ChartSeries;
    top_requesters: ChartSeries;
    sla_per_technician: ChartSeries;
  };
  alerts: OverviewAlert[];
}
