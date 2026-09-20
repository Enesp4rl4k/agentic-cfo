// Sector benchmark types. Moved out of the deleted kernels client, which was
// the only thing they shared a file with.

export interface BenchmarkItem {
  metric:          string;
  company_value:   number | null;
  benchmark_p25:   number;
  benchmark_p50:   number;
  benchmark_p75:   number;
  unit:            string;
  higher_is_better: boolean;
  percentile:      number | null;
  verdict:         string;
  gap_to_median:   number | null;
  context:         string;
}

export interface BenchmarkReport {
  sector:       string;
  company_size: string;
  items:        BenchmarkItem[];
  summary:      string;
  strengths:    string[];
  weaknesses:   string[];
  generated_at: string;
}
