import { ChartSeries, StackedChartData } from '../core/models/common.model';

/** Build a single-series chart from the top-N rows by a numeric field. */
export function topSeries<T extends object>(
  rows: T[],
  labelKey: keyof T,
  valueKey: keyof T,
  n = 15,
  label = '',
): ChartSeries {
  const top = [...rows]
    .sort((a, b) => Number(b[valueKey]) - Number(a[valueKey]))
    .slice(0, n);
  return {
    labels: top.map((r) => String(r[labelKey] ?? '')),
    values: top.map((r) => Number(r[valueKey]) || 0),
    label,
  };
}

/** Build a stacked chart (e.g. incidents vs requests) from the top-N rows. */
export function stackedSeries<T extends object>(
  rows: T[],
  labelKey: keyof T,
  parts: { key: keyof T; label: string; color?: string }[],
  sortKey: keyof T,
  n = 15,
): StackedChartData {
  const top = [...rows]
    .sort((a, b) => Number(b[sortKey]) - Number(a[sortKey]))
    .slice(0, n);
  return {
    labels: top.map((r) => String(r[labelKey] ?? '')),
    series: parts.map((p) => ({
      label: p.label,
      color: p.color,
      values: top.map((r) => Number(r[p.key]) || 0),
    })),
  };
}

/** Attach a 1-based rank to rows sorted by a numeric field (desc). */
export function withRank<T extends object>(rows: T[], sortKey: keyof T): T[] {
  return [...rows]
    .sort((a, b) => Number(b[sortKey]) - Number(a[sortKey]))
    .map((r, i) => ({ ...r, rank: i + 1 }));
}

/** Map a requester profile to a badge tone. */
export function profileTone(profile: string): string {
  const p = (profile || '').toLowerCase();
  if (p.includes('autonome')) return 'success';
  if (p.includes('standard')) return 'info';
  if (p.includes('depend')) return 'warning';
  if (p.includes('crit')) return 'danger';
  return 'neutral';
}
