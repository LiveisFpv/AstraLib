export interface TokenResReq {
  access_token: string
}

export interface UserLoginRequest {
  login: string
  password: string
}

export interface UserRegisterRequest {
  email: string
  first_name: string
  last_name: string
  password: string
}

export interface PasswordResetRequest {
  email: string
}

export interface PasswordResetResponse {
  message?: string
}

export interface UserResponse {
  id?: number
  email: string
  email_confirmed: boolean
  first_name: string
  last_name: string
  locale_type?: string
  photo?: string
  roles: string[]
}

export interface User {
  id?: number
  email: string
  email_confirmed: boolean
  first_name: string
  last_name: string
  locale_type?: string
  photo?: string
  roles: string[]
}

export interface ErrorResponse {
  error: string
}

export interface UserUpdateRequest {
  email?: string
  first_name?: string
  last_name?: string
  locale_type?: string
  password?: string
}

export interface UserUpdateRequestWithRoles {
  email?: string
  first_name?: string
  last_name?: string
  locale_type?: string
  password?: string
  roles?: string[]
}

// Admin: list users response
export interface UserListResponse {
  items: UserResponse[]
  limit: number
  page: number
  total: number
}

// Admin: list users query
export interface UserListQuery {
  q?: string
  role?: string
  email_confirmed?: boolean
  locale?: string
  page?: number
  limit?: number
}

export interface CreateChatRequest {
  user_id?: number
  title: string
}

export interface ChatResponse {
  chat_id: number
  user_id: number
  updated_at: string
  title: string
}

export interface ChatsResponse {
  chats: ChatResponse[]
}

export interface ChatHistoryCreateRequest {
  text: string
}

export interface ChatHistoryMessage {
  search_query: string
  created_at: string
  updated_at?: string
  papers: ChatPaperResponse[]
}

export interface ChatHistoryResponse {
  chat_messages: ChatHistoryMessage[]
}

export interface PapersResponse {
  papers?: PaperResponse[]
}

export interface ChatPaperResponse {
  abstract?: string
  authors?: string[]
  best_oa_location?: string
  cited_by_count?: number
  id?: string
  identifiers?: PaperIdentifier[]
  institutions?: string[]
  referenced_works?: string[]
  related_works?: string[]
  title?: string
  year?: number
  state?: string
  score: number
}

export interface PaperResponse {
  abstract?: string
  authors?: string[]
  best_oa_location?: string
  cited_by_count?: number
  id?: string
  identifiers?: PaperIdentifier[]
  institutions?: string[]
  referenced_works?: string[]
  related_works?: string[]
  title?: string
  year?: number
  state?: string
}

export interface PaperIdentifier {
  type?: string
  value?: string
}

export type SubmissionStatus = 'draft' | 'pending' | 'approved' | 'rejected'

export interface SubmissionRecord {
  submission_id: number
  created_by_user_id: number
  source_identifier?: string
  title?: string
  abstract?: string
  year?: number
  best_oa_location?: string
  referenced_works: string[]
  related_works: string[]
  status: SubmissionStatus
  moderated_by_user_id?: number
  moderation_comment?: string
  approved_paper_id?: number
  created_at?: string
  updated_at?: string
  submitted_at?: string
  moderated_at?: string
}

export interface SubmissionResponse {
  submission: SubmissionRecord
}

export interface SubmissionListResponse {
  items: SubmissionRecord[]
  total: number
  limit: number
  offset: number
}

export interface SubmissionListQuery {
  statuses?: SubmissionStatus[]
  limit?: number
  offset?: number
}

export interface SubmissionUpsertRequest {
  source_identifier?: string
  title?: string
  abstract?: string
  year?: number
  best_oa_location?: string
  referenced_works: string[]
  related_works: string[]
}

export interface ModerateSubmissionRequest {
  action: 'approve' | 'reject'
  comment?: string
}
