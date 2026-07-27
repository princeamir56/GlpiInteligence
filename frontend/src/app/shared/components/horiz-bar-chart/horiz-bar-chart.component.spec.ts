import { TestBed } from '@angular/core/testing';
import { HorizBarChartComponent } from './horiz-bar-chart.component';
import { commonTestProviders } from '../../../testing/test-providers';

describe('HorizBarChartComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [HorizBarChartComponent],
      providers: [commonTestProviders],
    }).compileComponents();
  });

  it('should create', () => {
    const fixture = TestBed.createComponent(HorizBarChartComponent);
    fixture.detectChanges();
    expect(fixture.componentInstance).toBeTruthy();
  });
});
