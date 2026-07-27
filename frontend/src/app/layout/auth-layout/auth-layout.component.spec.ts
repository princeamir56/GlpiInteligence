import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';
import { AuthLayoutComponent } from './auth-layout.component';
import { commonTestProviders } from '../../testing/test-providers';

describe('AuthLayoutComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AuthLayoutComponent],
      providers: [commonTestProviders],
    }).compileComponents();
  });

  afterEach(() => {
    const httpMock = TestBed.inject(HttpTestingController);
    httpMock.match(() => true).forEach((r) => r.flush([]));
    httpMock.verify();
  });

  it('should create', () => {
    const fixture = TestBed.createComponent(AuthLayoutComponent);
    fixture.detectChanges();
    expect(fixture.componentInstance).toBeTruthy();
  });
});
