import { Component, Input } from '@angular/core';
import { NgIf } from '@angular/common';
import { LucideAngularModule } from 'lucide-angular';
import { CountUpDirective } from '../../directives/count-up.directive';

/** KPI tile with an animated count-up value and optional trend delta. */
@Component({
  selector: 'app-kpi-card',
  standalone: true,
  imports: [NgIf, LucideAngularModule, CountUpDirective],
  templateUrl: './kpi-card.component.html',
  styleUrl: './kpi-card.component.css',
})
export class KpiCardComponent {
  @Input() label = '';
  @Input() value = 0;
  @Input() unit = '';
  @Input() icon = 'layout-dashboard';
  @Input() decimals = 0;
  @Input() delta?: number;
  @Input() trend?: 'up' | 'down' | 'flat';

  /** For most KPIs "up" is good; pass false where up is bad (e.g. open tickets). */
  @Input() upIsGood = true;

  get trendTone(): 'good' | 'bad' | 'flat' {
    const t = this.trend ?? (this.delta == null ? 'flat' : this.delta > 0 ? 'up' : this.delta < 0 ? 'down' : 'flat');
    if (t === 'flat') return 'flat';
    const isUp = t === 'up';
    return isUp === this.upIsGood ? 'good' : 'bad';
  }

  get trendIcon(): string {
    const t = this.trend ?? (this.delta == null ? 'flat' : this.delta > 0 ? 'up' : this.delta < 0 ? 'down' : 'flat');
    return t === 'up' ? 'arrow-up' : t === 'down' ? 'arrow-down' : 'minus';
  }
}
