/** Shared query params accepted by every tab endpoint. */
export interface TabQuery {
  start_date?: string;
  end_date?: string;
  limit?: number;
  entity_id?: number;
  category_id?: number;
}

/** Generic chart dataset used by the chart wrapper components. */
export interface ChartSeries {
  labels: string[];
  values: number[];
  label?: string;
}

export interface StackedChartData {
  labels: string[];
  series: { label: string; values: number[]; color?: string }[];
}

export type Severity = 'CRITIQUE' | 'ELEVE' | 'MOYEN' | 'FAIBLE';
