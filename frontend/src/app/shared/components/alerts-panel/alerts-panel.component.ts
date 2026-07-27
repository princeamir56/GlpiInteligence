import { Component, EventEmitter, Input, Output } from '@angular/core';
import { NgFor, NgIf } from '@angular/common';
import { LucideAngularModule } from 'lucide-angular';
import { OverviewAlert } from '../../../core/models/overview.model';
import { SkeletonLoaderComponent } from '../skeleton-loader/skeleton-loader.component';
import { StaggerDirective } from '../../directives/stagger.directive';

/** ML alerts list (Overview tab). Emits acknowledge events per alert. */
@Component({
  selector: 'app-alerts-panel',
  standalone: true,
  imports: [NgFor, NgIf, LucideAngularModule, SkeletonLoaderComponent, StaggerDirective],
  templateUrl: './alerts-panel.component.html',
  styleUrl: './alerts-panel.component.css',
})
export class AlertsPanelComponent {
  @Input() alerts: OverviewAlert[] = [];
  @Input() loading = false;
  @Output() acknowledge = new EventEmitter<OverviewAlert>();

  severityClass(sev: string): string {
    const s = (sev || '').toLowerCase();
    if (s.includes('crit')) return 'critique';
    if (s.includes('lev') || s.includes('elev') || s.includes('high')) return 'eleve';
    if (s.includes('moy') || s.includes('med')) return 'moyen';
    return 'faible';
  }
}
