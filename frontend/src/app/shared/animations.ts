import {
  trigger,
  transition,
  style,
  animate,
  query,
  stagger,
  state,
} from '@angular/animations';

/** 250ms cross-fade + 12px vertical slide for route transitions. */
export const routeFade = trigger('routeFade', [
  transition('* <=> *', [
    style({ opacity: 0, transform: 'translateY(12px)' }),
    animate('250ms cubic-bezier(0.16,1,0.3,1)', style({ opacity: 1, transform: 'translateY(0)' })),
  ]),
]);

/** Staggered fade-up for a list of sibling cards (60ms between children). */
export const staggerCards = trigger('staggerCards', [
  transition(':enter', [
    query(
      ':enter',
      [
        style({ opacity: 0, transform: 'translateY(14px)' }),
        stagger(60, [
          animate(
            '360ms cubic-bezier(0.16,1,0.3,1)',
            style({ opacity: 1, transform: 'translateY(0)' }),
          ),
        ]),
      ],
      { optional: true },
    ),
  ]),
]);

/** Single element fade-up on enter. */
export const fadeUp = trigger('fadeUp', [
  transition(':enter', [
    style({ opacity: 0, transform: 'translateY(10px)' }),
    animate('300ms cubic-bezier(0.16,1,0.3,1)', style({ opacity: 1, transform: 'translateY(0)' })),
  ]),
]);

/** Expand/collapse used by the sidebar & dropdowns. */
export const expandCollapse = trigger('expandCollapse', [
  state('collapsed', style({ height: '0', opacity: 0, overflow: 'hidden' })),
  state('expanded', style({ height: '*', opacity: 1 })),
  transition('collapsed <=> expanded', animate('280ms cubic-bezier(0.16,1,0.3,1)')),
]);
