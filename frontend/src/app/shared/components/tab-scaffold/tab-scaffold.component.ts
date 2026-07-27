import { Component, EventEmitter, Input, Output } from '@angular/core';
import { NgIf } from '@angular/common';
import { LucideAngularModule } from 'lucide-angular';
import { fadeUp } from '../../animations';

/**
 * Common tab frame: page title/subtitle, an error state with retry, and a
 * content slot. Individual tabs project their charts + table inside.
 */
@Component({
  selector: 'app-tab-scaffold',
  standalone: true,
  imports: [NgIf, LucideAngularModule],
  templateUrl: './tab-scaffold.component.html',
  styleUrl: './tab-scaffold.component.css',
  animations: [fadeUp],
})
export class TabScaffoldComponent {
  @Input() title = '';
  @Input() subtitle = '';
  @Input() error = false;
  @Output() retry = new EventEmitter<void>();
}
