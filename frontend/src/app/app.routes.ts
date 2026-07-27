import { Routes } from '@angular/router';
import { authGuard } from './core/guards/auth.guard';
import { roleGuard } from './core/guards/role.guard';

export const routes: Routes = [
  {
    path: 'login',
    loadComponent: () =>
      import('./layout/auth-layout/auth-layout.component').then((m) => m.AuthLayoutComponent),
    children: [
      {
        path: '',
        loadComponent: () =>
          import('./pages/login/login.component').then((m) => m.LoginComponent),
      },
    ],
  },
  {
    path: '',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./layout/main-layout/main-layout.component').then((m) => m.MainLayoutComponent),
    children: [
      { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
      {
        path: 'dashboard',
        loadComponent: () =>
          import('./pages/dashboard/dashboard.component').then((m) => m.DashboardComponent),
      },
      {
        path: 'demandeurs',
        loadComponent: () =>
          import('./pages/demandeurs/demandeurs.component').then((m) => m.DemandeursComponent),
      },
      {
        path: 'services',
        loadComponent: () =>
          import('./pages/services/services.component').then((m) => m.ServicesComponent),
      },
      {
        path: 'sites',
        loadComponent: () => import('./pages/sites/sites.component').then((m) => m.SitesComponent),
      },
      {
        path: 'repetitifs',
        loadComponent: () =>
          import('./pages/repetitifs/repetitifs.component').then((m) => m.RepetitifsComponent),
      },
      {
        path: 'techniciens',
        loadComponent: () =>
          import('./pages/techniciens/techniciens.component').then((m) => m.TechniciensComponent),
      },
      {
        path: 'categories',
        loadComponent: () =>
          import('./pages/categories/categories.component').then((m) => m.CategoriesComponent),
      },
      {
        path: 'settings',
        canActivate: [roleGuard],
        data: { roles: [] },
        loadComponent: () =>
          import('./pages/settings/settings.component').then((m) => m.SettingsComponent),
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
