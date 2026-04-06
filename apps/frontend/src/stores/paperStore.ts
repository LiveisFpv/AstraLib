import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { AlibApi } from '@/api/useAlibApi'
import type {
  SubmissionListQuery,
  SubmissionRecord,
  SubmissionStatus,
  SubmissionUpsertRequest,
} from '@/api/types'

export type PaperStatus = SubmissionStatus

export interface PaperLink {
  id: string
}

export interface PaperSummary {
  id: string
  title: string
  status: PaperStatus
  updatedAt: string
  submittedAt?: string
  moderatorComment?: string
  approvedPaperId?: number
}

export interface PaperDetail extends PaperSummary {
  source_identifier?: string
  abstract?: string
  year?: number
  best_oa_location?: string
  related_paper: PaperLink[]
  referenced_paper: PaperLink[]
  createdByUserId: number
  moderatedByUserId?: number
  createdAt?: string
  moderatedAt?: string
}

export interface PaperPayload {
  id?: string
  source_identifier?: string
  title?: string
  abstract?: string
  year?: number
  best_oa_location?: string
  related_paper?: PaperLink[]
  referenced_paper?: PaperLink[]
}

const EDITABLE_STATUSES = new Set<PaperStatus>(['draft', 'rejected'])

function normalizeLinkArray(values: string[] | undefined): PaperLink[] {
  return (values ?? []).map((value) => ({ id: value }))
}

function mapSubmission(submission: SubmissionRecord): PaperDetail {
  return {
    id: String(submission.submission_id),
    title: submission.title?.trim() || '',
    status: submission.status,
    updatedAt: submission.updated_at || '',
    submittedAt: submission.submitted_at || undefined,
    moderatorComment: submission.moderation_comment || undefined,
    approvedPaperId: submission.approved_paper_id || undefined,
    source_identifier: submission.source_identifier || undefined,
    abstract: submission.abstract || undefined,
    year: submission.year || undefined,
    best_oa_location: submission.best_oa_location || undefined,
    related_paper: normalizeLinkArray(submission.related_works),
    referenced_paper: normalizeLinkArray(submission.referenced_works),
    createdByUserId: submission.created_by_user_id,
    moderatedByUserId: submission.moderated_by_user_id || undefined,
    createdAt: submission.created_at || undefined,
    moderatedAt: submission.moderated_at || undefined,
  }
}

function mapSubmissionInput(payload: PaperPayload): SubmissionUpsertRequest {
  return {
    source_identifier: payload.source_identifier?.trim() || '',
    title: payload.title?.trim() || '',
    abstract: payload.abstract?.trim() || '',
    year: payload.year || 0,
    best_oa_location: payload.best_oa_location?.trim() || '',
    related_works: (payload.related_paper ?? [])
      .map((item) => item.id.trim())
      .filter((item) => item.length > 0),
    referenced_works: (payload.referenced_paper ?? [])
      .map((item) => item.id.trim())
      .filter((item) => item.length > 0),
  }
}

export const usePaperStore = defineStore('paper', () => {
  const items = ref<PaperDetail[]>([])
  const isLoading = ref(false)
  const lastLoaded = ref<string | null>(null)

  const papers = computed(() => items.value)

  const editablePaperIds = computed(() =>
    papers.value.filter((paper) => EDITABLE_STATUSES.has(paper.status)).map((paper) => paper.id),
  )

  function canEdit(id: string) {
    return editablePaperIds.value.includes(id)
  }

  function canDelete(id: string) {
    return canEdit(id)
  }

  function upsertPaper(submission: SubmissionRecord) {
    const next = mapSubmission(submission)
    const index = items.value.findIndex((paper) => paper.id === next.id)
    if (index >= 0) {
      items.value.splice(index, 1, next)
    } else {
      items.value.unshift(next)
    }
    return next
  }

  function getMyPapers(statuses?: PaperStatus[]): PaperSummary[] {
    const allowed = statuses?.length ? new Set(statuses) : null
    return papers.value
      .filter((paper) => !allowed || allowed.has(paper.status))
      .map((paper) => ({
        id: paper.id,
        title: paper.title,
        status: paper.status,
        updatedAt: paper.updatedAt,
        submittedAt: paper.submittedAt,
        moderatorComment: paper.moderatorComment,
        approvedPaperId: paper.approvedPaperId,
      }))
  }

  function getById(id: string) {
    return papers.value.find((paper) => paper.id === id)
  }

  async function loadMyPapers(query: SubmissionListQuery = {}) {
    if (isLoading.value) return
    isLoading.value = true
    try {
      const response = await AlibApi.listMySubmissions({
        limit: query.limit ?? 100,
        offset: query.offset ?? 0,
        statuses: query.statuses,
      })
      items.value = response.items.map(mapSubmission)
      lastLoaded.value = new Date().toISOString()
    } finally {
      isLoading.value = false
    }
  }

  async function fetchSubmission(id: string | number) {
    const response = await AlibApi.getMySubmission(id)
    return upsertPaper(response.submission)
  }

  async function saveDraft(payload: PaperPayload) {
    const request = mapSubmissionInput(payload)
    const response = payload.id
      ? await AlibApi.updateMySubmission(payload.id, request)
      : await AlibApi.createSubmission(request)
    return upsertPaper(response.submission)
  }

  async function submitExisting(id: string | number) {
    const response = await AlibApi.submitMySubmission(id)
    return upsertPaper(response.submission)
  }

  async function submitPaper(payload: PaperPayload) {
    const saved = await saveDraft(payload)
    return submitExisting(saved.id)
  }

  async function deletePaper(id: string | number) {
    await AlibApi.deleteMySubmission(id)
    items.value = items.value.filter((paper) => paper.id !== String(id))
  }

  function resetForLogout() {
    items.value = []
    lastLoaded.value = null
  }

  return {
    items,
    isLoading,
    lastLoaded,
    papers,
    editablePaperIds,
    canEdit,
    canDelete,
    loadMyPapers,
    getMyPapers,
    getById,
    fetchSubmission,
    saveDraft,
    submitExisting,
    submitPaper,
    deletePaper,
    upsertPaper,
    resetForLogout,
  }
})
