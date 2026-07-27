/**
 * Row shapes for the analytics tabs. Fields mirror the layer-4 responses as
 * described in the project brief; unknown extra fields are tolerated by the
 * table (it renders by column config). Adjust here if the API differs.
 */

export interface Demandeur {
  rank?: number;
  name: string;
  total: number;
  incidents: number;
  requests: number;
  open: number;
  repetitive: number;
  high_priority: number;
  tickets_per_month?: number;
  profile: string; // autonome | standard | dependant | critique
}

export interface ServiceRow {
  rank?: number;
  name: string;
  total: number;
  incidents: number;
  requests: number;
  open: number;
  sla_rate?: number;
  avg_resolution_days?: number;
}

export interface SiteRow {
  rank?: number;
  name: string;
  total: number;
  open: number;
  sla_rate?: number;
  avg_resolution_days?: number;
}

export interface CategoryRow {
  rank?: number;
  name: string;
  total: number;
  incidents: number;
  requests: number;
  open: number;
  sla_rate?: number;
}

export interface TechnicianRow {
  rank?: number;
  name: string;
  total: number;
  open: number;
  avg_resolution_days: number;
  sla_rate: number;
}

export interface RepetitiveRow {
  rank?: number;
  cluster_id?: number | string;
  title: string;
  count: number;
  keywords?: string[];
  sample_titles?: string[];
  category?: string;
}
