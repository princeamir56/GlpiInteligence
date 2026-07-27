import { ComponentFixture, TestBed } from '@angular/core/testing';
import { SkeletonLoaderComponent } from './skeleton-loader.component';

describe('SkeletonLoaderComponent', () => {
  let fixture: ComponentFixture<SkeletonLoaderComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [SkeletonLoaderComponent] }).compileComponents();
    fixture = TestBed.createComponent(SkeletonLoaderComponent);
  });

  it('should create', () => {
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('should render one placeholder per count', () => {
    fixture.componentInstance.count = 4;
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelectorAll('.sk').length).toBe(4);
  });
});
