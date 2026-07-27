import { TestBed } from '@angular/core/testing';
import { DonutChartComponent } from './donut-chart.component';
import { commonTestProviders } from '../../../testing/test-providers';

describe('DonutChartComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DonutChartComponent],
      providers: [commonTestProviders],
    }).compileComponents();
  });

  it('should create', () => {
    const fixture = TestBed.createComponent(DonutChartComponent);
    fixture.detectChanges();
    expect(fixture.componentInstance).toBeTruthy();
  });
});
