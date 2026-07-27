import { TestBed } from '@angular/core/testing';
import { BarChartComponent } from './bar-chart.component';
import { commonTestProviders } from '../../../testing/test-providers';

describe('BarChartComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [BarChartComponent],
      providers: [commonTestProviders],
    }).compileComponents();
  });

  it('should create', () => {
    const fixture = TestBed.createComponent(BarChartComponent);
    fixture.detectChanges();
    expect(fixture.componentInstance).toBeTruthy();
  });
});
