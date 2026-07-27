import { Component, Input, computed, signal } from '@angular/core';
import {
  NgFor, NgIf, NgClass, NgSwitch, NgSwitchCase, NgSwitchDefault, DecimalPipe,
} from '@angular/common';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';
import { BadgeComponent, BadgeTone } from '../badge/badge.component';
import { SlaBarComponent } from '../sla-bar/sla-bar.component';
import { SkeletonLoaderComponent } from '../skeleton-loader/skeleton-loader.component';
import { TableColumn } from './data-table.model';

type Row = Record<string, unknown>;

/** Reusable sortable / searchable / CSV-exportable table. */
@Component({
  selector: 'app-data-table',
  standalone: true,
  imports: [
    NgFor, NgIf, NgClass, NgSwitch, NgSwitchCase, NgSwitchDefault, DecimalPipe, FormsModule,
    LucideAngularModule, BadgeComponent, SlaBarComponent, SkeletonLoaderComponent,
  ],
  templateUrl: './data-table.component.html',
  styleUrl: './data-table.component.css',
})
export class DataTableComponent {
  @Input() columns: TableColumn[] = [];
  @Input() title = '';
  @Input() searchable = true;
  @Input() exportable = true;
  @Input() exportName = 'export';
  @Input() loading = false;
  @Input() pageSize = 12;

  private _rows = signal<Row[]>([]);
  /** Accepts any object array; typed tab models pass through without an index signature. */
  @Input() set rows(value: readonly object[] | null) {
    this._rows.set((value ?? []) as Row[]);
    this.page.set(1);
  }

  readonly search = signal('');
  readonly sortKey = signal<string | null>(null);
  readonly sortDir = signal<'asc' | 'desc'>('asc');
  readonly page = signal(1);

  readonly filtered = computed(() => {
    const q = this.search().trim().toLowerCase();
    let data = this._rows();
    if (q) {
      data = data.filter((row) =>
        this.columns.some((c) => String(row[c.key] ?? '').toLowerCase().includes(q)),
      );
    }
    const key = this.sortKey();
    if (key) {
      const dir = this.sortDir() === 'asc' ? 1 : -1;
      data = [...data].sort((a, b) => {
        const av = a[key], bv = b[key];
        if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir;
        return String(av ?? '').localeCompare(String(bv ?? ''), 'fr', { numeric: true }) * dir;
      });
    }
    return data;
  });

  readonly totalPages = computed(() => Math.max(1, Math.ceil(this.filtered().length / this.pageSize)));
  readonly paged = computed(() => {
    const start = (this.page() - 1) * this.pageSize;
    return this.filtered().slice(start, start + this.pageSize);
  });

  sortBy(col: TableColumn): void {
    if (col.sortable === false) return;
    if (this.sortKey() === col.key) {
      this.sortDir.update((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      this.sortKey.set(col.key);
      this.sortDir.set('asc');
    }
    this.page.set(1);
  }

  prev(): void { this.page.update((p) => Math.max(1, p - 1)); }
  next(): void { this.page.update((p) => Math.min(this.totalPages(), p + 1)); }

  cellText(col: TableColumn, row: Row): string {
    const raw = row[col.key];
    if (col.format) return col.format(raw, row);
    return raw == null ? '—' : String(raw);
  }

  badgeTone(col: TableColumn, row: Row): BadgeTone {
    return (col.badgeTone?.(row) as BadgeTone) ?? 'neutral';
  }
  badgeLabel(col: TableColumn, row: Row): string {
    return col.badgeLabel?.(row) ?? String(row[col.key] ?? '');
  }
  numberVal(col: TableColumn, row: Row): number {
    const v = Number(row[col.key]);
    return isNaN(v) ? 0 : v;
  }

  exportCsv(): void {
    const cols = this.columns;
    const header = cols.map((c) => this.csvCell(c.label)).join(',');
    const lines = this.filtered().map((row) =>
      cols.map((c) => this.csvCell(this.cellText(c, row))).join(','),
    );
    const csv = [header, ...lines].join('\r\n');
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${this.exportName}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  private csvCell(v: string): string {
    const s = String(v ?? '');
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }
}
