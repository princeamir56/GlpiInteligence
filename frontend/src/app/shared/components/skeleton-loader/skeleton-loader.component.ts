import { Component, Input } from '@angular/core';
import { NgFor } from '@angular/common';

type SkeletonVariant = 'text' | 'card' | 'kpi' | 'chart' | 'table-row' | 'circle';

/** Shimmer placeholder used while data loads (no spinners). */
@Component({
  selector: 'app-skeleton-loader',
  standalone: true,
  imports: [NgFor],
  templateUrl: './skeleton-loader.component.html',
  styleUrl: './skeleton-loader.component.css',
})
export class SkeletonLoaderComponent {
  @Input() variant: SkeletonVariant = 'text';
  @Input() count = 1;
  @Input() width = '100%';
  @Input() height = '';

  get items(): number[] {
    return Array.from({ length: this.count }, (_, i) => i);
  }
}
