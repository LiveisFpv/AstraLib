import { api } from '@/api/base/useAlibApi'
import type {
  ChatHistoryMessage,
  ChatHistoryCreateRequest,
  ChatHistoryResponse,
  ChatResponse,
  ChatsResponse,
  CreateChatRequest,
  ModerateSubmissionRequest,
  SubmissionListQuery,
  SubmissionListResponse,
  SubmissionResponse,
  SubmissionUpsertRequest,
} from './types'

export const AlibApi = {
  search(search_text: string, chat_id: number) {
    const id = `${encodeURIComponent(chat_id)}`
    const payload = <ChatHistoryCreateRequest>{
      text: search_text,
    }
    return api.post<ChatHistoryMessage>(`/chats/${id}/history`, payload).then((r) => r.data)
  },
  get_chat_history(chat_id: number) {
    const id = `${encodeURIComponent(chat_id)}`
    return api.get<ChatHistoryResponse>(`/chats/${id}/history`).then((r) => r.data)
  },
  create_chat(chat_name: string) {
    const payload = <CreateChatRequest>{
      title: chat_name,
    }
    return api.post<ChatResponse>(`/chats/`, payload).then((r) => r.data)
  },
  update_chat(chat_id: number, title: string) {
    const id = `${encodeURIComponent(chat_id)}`
    const payload = <CreateChatRequest>{
      title: title,
    }
    return api.put<ChatResponse>(`/chats/${id}`, payload).then((r) => r.data)
  },
  delete_chat(chat_id: number) {
    const id = `${encodeURIComponent(chat_id)}`
    return api.delete<void>(`/chats/${id}`).then((r) => r.data)
  },
  get_all_user_chats() {
    return api.get<ChatsResponse>(`/chats/`).then((r) => r.data)
  },
  createSubmission(payload: SubmissionUpsertRequest) {
    return api.post<SubmissionResponse>('/submissions', payload).then((r) => r.data)
  },
  listMySubmissions(query: SubmissionListQuery = {}) {
    const params: Record<string, string | number> = {}
    if (query.statuses?.length) params.statuses = query.statuses.join(',')
    if (typeof query.limit === 'number') params.limit = query.limit
    if (typeof query.offset === 'number') params.offset = query.offset
    return api.get<SubmissionListResponse>('/submissions', { params }).then((r) => r.data)
  },
  getMySubmission(submissionId: string | number) {
    const id = `${encodeURIComponent(String(submissionId))}`
    return api.get<SubmissionResponse>(`/submissions/${id}`).then((r) => r.data)
  },
  updateMySubmission(submissionId: string | number, payload: SubmissionUpsertRequest) {
    const id = `${encodeURIComponent(String(submissionId))}`
    return api.put<SubmissionResponse>(`/submissions/${id}`, payload).then((r) => r.data)
  },
  deleteMySubmission(submissionId: string | number) {
    const id = `${encodeURIComponent(String(submissionId))}`
    return api.delete<void>(`/submissions/${id}`).then((r) => r.data)
  },
  submitMySubmission(submissionId: string | number) {
    const id = `${encodeURIComponent(String(submissionId))}`
    return api.post<SubmissionResponse>(`/submissions/${id}/submit`).then((r) => r.data)
  },
  listModerationSubmissions(query: SubmissionListQuery = {}) {
    const params: Record<string, string | number> = {}
    if (query.statuses?.length) params.statuses = query.statuses.join(',')
    if (typeof query.limit === 'number') params.limit = query.limit
    if (typeof query.offset === 'number') params.offset = query.offset
    return api
      .get<SubmissionListResponse>('/moderation/submissions', { params })
      .then((r) => r.data)
  },
  getModerationSubmission(submissionId: string | number) {
    const id = `${encodeURIComponent(String(submissionId))}`
    return api.get<SubmissionResponse>(`/moderation/submissions/${id}`).then((r) => r.data)
  },
  updateModerationSubmission(submissionId: string | number, payload: SubmissionUpsertRequest) {
    const id = `${encodeURIComponent(String(submissionId))}`
    return api.put<SubmissionResponse>(`/moderation/submissions/${id}`, payload).then((r) => r.data)
  },
  moderateSubmission(submissionId: string | number, payload: ModerateSubmissionRequest) {
    const id = `${encodeURIComponent(String(submissionId))}`
    return api
      .post<SubmissionResponse>(`/moderation/submissions/${id}/moderate`, payload)
      .then((r) => r.data)
  },
}
