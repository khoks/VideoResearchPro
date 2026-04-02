import { create } from 'zustand';

interface JobStore {
  activeJobId: string | null;
  isReportModalOpen: boolean;
  activeTab: 'submit' | 'jobs';
  setActiveJob: (id: string | null) => void;
  openReportModal: () => void;
  closeReportModal: () => void;
  setActiveTab: (tab: 'submit' | 'jobs') => void;
}

export const useJobStore = create<JobStore>((set) => ({
  activeJobId: null,
  isReportModalOpen: false,
  activeTab: 'submit',
  setActiveJob: (id) => set({ activeJobId: id }),
  openReportModal: () => set({ isReportModalOpen: true }),
  closeReportModal: () => set({ isReportModalOpen: false }),
  setActiveTab: (tab) => set({ activeTab: tab }),
}));
