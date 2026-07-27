/**
 * Reads live theme colors from CSS custom properties so charts restyle when
 * the theme toggles. Also exposes the categorical brand palette for series.
 */
export function cssVar(name: string, fallback = ''): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

export interface ChartTheme {
  text: string;
  muted: string;
  grid: string;
  surface: string;
  categorical: string[];
  primary: string;
}

export function readChartTheme(): ChartTheme {
  return {
    text: cssVar('--text-base', '#292524'),
    muted: cssVar('--text-muted', '#78716c'),
    grid: cssVar('--border-color', 'rgba(0,0,0,0.08)'),
    surface: cssVar('--bg-surface', '#ffffff'),
    primary: cssVar('--primary-500', '#5b69bc'),
    categorical: [
      cssVar('--primary-500', '#5b69bc'),
      cssVar('--info', '#3b82f6'),
      cssVar('--success', '#10b981'),
      cssVar('--warning', '#f59e0b'),
      cssVar('--primary-300', '#a6afe0'),
      cssVar('--danger', '#ef4444'),
      cssVar('--primary-700', '#323e8a'),
      '#8b5cf6',
    ],
  };
}

/** Applies alpha to a hex color (#rrggbb) → rgba string. */
export function withAlpha(hex: string, alpha: number): string {
  const h = hex.replace('#', '');
  if (h.length !== 6) return hex;
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
