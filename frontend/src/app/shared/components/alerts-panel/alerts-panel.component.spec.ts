import { TestBed } from '@angular/core/testing';
import { AlertsPanelComponent } from './alerts-panel.component';
import { commonTestProviders } from '../../../testing/test-providers';

describe('AlertsPanelComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AlertsPanelComponent],
      providers: [commonTestProviders],
    }).compileComponents();
  });

  it('should create', () => {
    const fixture = TestBed.createComponent(AlertsPanelComponent);
    fixture.detectChanges();
    expect(fixture.componentInstance).toBeTruthy();
  });
});
