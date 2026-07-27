import { Component, Input, computed, signal } from '@angular/core';
import { NgIf, NgClass } from '@angular/common';

export type BadgeTone = 'success' | 'warning' | 'danger' | 'info' | 'neutral' | 'primary';

/** Colored pill for severities, profiles, statuses. */
@Component({
  selector: 'app-badge',
  standalone: true,
  imports: [NgIf, NgClass],
  templateUrl: './badge.component.html',
  styleUrl: './badge.component.css',
})
export class BadgeComponent {
  private _tone = signal<BadgeTone>('neutral');
  @Input() set tone(value: BadgeTone) {
    this._tone.set(value);
  }
  @Input() label = '';
  @Input() dot = false;

  readonly toneClass = computed(() => `tone-${this._tone()}`);
}
