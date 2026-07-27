import { Component, Input } from '@angular/core';
import { NgIf } from '@angular/common';
import { LucideAngularModule } from 'lucide-angular';
import { fadeUp } from '../../animations';

/** Temporary page shell shown while a tab's real content is being wired. */
@Component({
  selector: 'app-placeholder-page',
  standalone: true,
  imports: [NgIf, LucideAngularModule],
  templateUrl: './placeholder-page.component.html',
  styleUrl: './placeholder-page.component.css',
  animations: [fadeUp],
})
export class PlaceholderPageComponent {
  @Input() title = '';
  @Input() subtitle = '';
}
