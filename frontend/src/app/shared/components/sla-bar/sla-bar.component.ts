import { Component, Input, computed, signal } from '@angular/core';
import { NgIf, DecimalPipe } from '@angular/common';

/** Inline SLA progress bar. Green >= 90, amber >= 70, red below. */
@Component({
  selector: 'app-sla-bar',
  standalone: true,
  imports: [NgIf, DecimalPipe],
  templateUrl: './sla-bar.component.html',
  styleUrl: './sla-bar.component.css',
})
export class SlaBarComponent {
  private _value = signal(0);
  @Input() set value(v: number) {
    this._value.set(Math.max(0, Math.min(100, v ?? 0)));
  }
  @Input() showLabel = true;

  readonly pct = computed(() => this._value());
  readonly tone = computed(() => {
    const v = this._value();
    return v >= 90 ? 'good' : v >= 70 ? 'warn' : 'bad';
  });
}
