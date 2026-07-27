import { Role } from '../core/models/auth.model';

export interface NavItem {
  path: string;
  label: string;
  icon: string; // lucide icon name
  roles?: Role[]; // undefined = all roles
}

/** Primary sidebar navigation (the 7 analytics tabs). */
export const NAV_ITEMS: NavItem[] = [
  { path: '/dashboard', label: "Vue d'ensemble", icon: 'layout-dashboard' },
  { path: '/demandeurs', label: 'Demandeurs', icon: 'users' },
  { path: '/services', label: 'Services', icon: 'building-2' },
  { path: '/sites', label: 'Sites', icon: 'map-pin' },
  { path: '/repetitifs', label: 'Répétitifs', icon: 'repeat' },
  { path: '/techniciens', label: 'Techniciens', icon: 'wrench' },
  { path: '/categories', label: 'Catégories', icon: 'tags' },
];

export const FOOTER_NAV: NavItem[] = [
  { path: '/settings', label: 'Paramètres', icon: 'settings' },
];
