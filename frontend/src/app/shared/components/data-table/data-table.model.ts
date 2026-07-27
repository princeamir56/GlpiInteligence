export type ColumnType = 'text' | 'number' | 'badge' | 'sla' | 'rank' | 'template';

export interface TableColumn<T = Record<string, unknown>> {
  key: string;
  label: string;
  type?: ColumnType;
  sortable?: boolean;
  align?: 'left' | 'right' | 'center';
  /** For badge columns: map a row to a tone. */
  badgeTone?: (row: T) => string;
  /** For badge columns: map a row to a display label (defaults to the cell value). */
  badgeLabel?: (row: T) => string;
  /** Optional value formatter for text/number cells. */
  format?: (value: unknown, row: T) => string;
  width?: string;
}
