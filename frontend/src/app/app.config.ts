import { ApplicationConfig, importProvidersFrom } from '@angular/core';
import { provideRouter, withInMemoryScrolling } from '@angular/router';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideAnimations } from '@angular/platform-browser/animations';
import { Chart, registerables } from 'chart.js';

Chart.register(...registerables);
import {
  LucideAngularModule,
  LayoutDashboard,
  Users,
  Building2,
  MapPin,
  Repeat,
  Wrench,
  Tags,
  Settings,
  Sun,
  Moon,
  Bell,
  Search,
  LogOut,
  ChevronDown,
  ChevronsLeft,
  Menu,
  User,
  Download,
  ArrowUp,
  ArrowDown,
  ArrowRight,
  Minus,
  Check,
  CheckCheck,
  AlertTriangle,
  Inbox,
  Loader,
  X,
  Lock,
  Mail,
} from 'lucide-angular';

import { routes } from './app.routes';
import { jwtInterceptor } from './core/interceptors/jwt.interceptor';
import { refreshInterceptor } from './core/interceptors/refresh.interceptor';
import { errorInterceptor } from './core/interceptors/error.interceptor';

export const ICONS = {
  LayoutDashboard, Users, Building2, MapPin, Repeat, Wrench, Tags, Settings,
  Sun, Moon, Bell, Search, LogOut, ChevronDown, ChevronsLeft, Menu, User,
  Download, ArrowUp, ArrowDown, ArrowRight, Minus, Check, CheckCheck,
  AlertTriangle, Inbox, Loader, X, Lock, Mail,
};

export const appConfig: ApplicationConfig = {
  providers: [
    provideRouter(
      routes,
      withInMemoryScrolling({ scrollPositionRestoration: 'enabled' }),
    ),
    provideHttpClient(
      withInterceptors([jwtInterceptor, refreshInterceptor, errorInterceptor]),
    ),
    provideAnimations(),
    importProvidersFrom(LucideAngularModule.pick(ICONS)),
  ],
};
