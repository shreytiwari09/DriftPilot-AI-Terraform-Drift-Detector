import type { DashboardData, Episode, Filters, Kpis } from '../types';

export interface PageProps {
  data: DashboardData;
  filters: Filters;
  eps: Episode[];
  kpis: Kpis;
  open: (e: Episode) => void;
  setFilters: (f: Filters) => void;
}
