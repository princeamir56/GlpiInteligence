import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';
import { SitesComponent } from './sites.component';
import { commonTestProviders } from '../../testing/test-providers';

describe('SitesComponent', () => {
  let fixture: ComponentFixture<SitesComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [SitesComponent],
      providers: [commonTestProviders],
    }).compileComponents();
    fixture = TestBed.createComponent(SitesComponent);
    fixture.detectChanges();
  });

  afterEach(() => {
    const httpMock = TestBed.inject(HttpTestingController);
    httpMock.match(() => true).forEach((r) => r.flush([]));
    httpMock.verify();
  });

  it('should create', () => {
    expect(fixture.componentInstance).toBeTruthy();
  });
});
