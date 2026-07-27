import { ComponentFixture, TestBed } from '@angular/core/testing';
import { KpiCardComponent } from './kpi-card.component';
import { commonTestProviders } from '../../../testing/test-providers';

describe('KpiCardComponent', () => {
  let fixture: ComponentFixture<KpiCardComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [KpiCardComponent],
      providers: [commonTestProviders],
    }).compileComponents();
    fixture = TestBed.createComponent(KpiCardComponent);
  });

  it('should create', () => {
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('should display the label', () => {
    fixture.componentInstance.label = 'Tickets ouverts';
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Tickets ouverts');
  });

  it('should mark a positive delta as good when upIsGood', () => {
    fixture.componentInstance.delta = 5;
    fixture.componentInstance.upIsGood = true;
    expect(fixture.componentInstance.trendTone).toBe('good');
  });
});
