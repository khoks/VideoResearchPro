import api from './api';
import type { QAHistoryChatRequest, QAHistoryExchange } from '../types/qa';

export const qaHistoryApi = {
  getExchanges: () =>
    api.get<QAHistoryExchange[]>('/qa-history/exchanges').then(r => r.data),
  postChat: (data: QAHistoryChatRequest) =>
    api.post<QAHistoryExchange>('/qa-history/chat', data).then(r => r.data),
};
