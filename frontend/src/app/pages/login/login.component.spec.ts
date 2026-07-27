import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';
import { LoginComponent } from './login.component';
import { commonTestProviders } from '../../testing/test-providers';

describe('LoginComponent', () => {
  let fixture: ComponentFixture<LoginComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [LoginComponent],
      providers: [commonTestProviders],
    }).compileComponents();
    fixture = TestBed.createComponent(LoginComponent);
    fixture.detectChanges();
  });

  afterEach(() => {
    const httpMock = TestBed.inject(HttpTestingController);
    httpMock.match(() => true).forEach((r) => r.flush({}));
    httpMock.verify();
  });

  it('should create', () => {
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('should keep the form invalid until fields are filled', () => {
    const cmp = fixture.componentInstance;
    expect(cmp.form.invalid).toBe(true);
    cmp.form.setValue({ username: 'dsi@sartex', password: 'secret', remember: true });
    expect(cmp.form.valid).toBe(true);
  });
});
