import { Component, EventEmitter, Input, Output, inject } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { NgClass, NgFor } from '@angular/common';
import { LucideAngularModule } from 'lucide-angular';
import { NAV_ITEMS, FOOTER_NAV } from '../nav.config';
import { AuthService } from '../../core/services/auth.service';

@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [RouterLink, RouterLinkActive, NgClass, NgFor, LucideAngularModule],
  templateUrl: './sidebar.component.html',
  styleUrl: './sidebar.component.css',
})
export class SidebarComponent {
  @Input() collapsed = false;
  @Output() logout = new EventEmitter<void>();

  private auth = inject(AuthService);
  readonly navItems = NAV_ITEMS;
  readonly footerNav = FOOTER_NAV;

  get canSee() {
    return (roles?: string[]) => !roles || this.auth.hasRole(roles as never);
  }
}
