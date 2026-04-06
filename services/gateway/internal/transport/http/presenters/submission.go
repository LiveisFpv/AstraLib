package presenters

type SubmissionUpsertRequest struct {
	SourceIdentifier string   `json:"source_identifier"`
	Title            string   `json:"title"`
	Abstract         string   `json:"abstract"`
	Year             int      `json:"year"`
	BestOALocation   string   `json:"best_oa_location"`
	ReferencedWorks  []string `json:"referenced_works"`
	RelatedWorks     []string `json:"related_works"`
}

type SubmissionResponse struct {
	Submission SubmissionRecord `json:"submission"`
}

type SubmissionRecord struct {
	SubmissionID      int64    `json:"submission_id"`
	CreatedByUserID   int64    `json:"created_by_user_id"`
	SourceIdentifier  string   `json:"source_identifier"`
	Title             string   `json:"title"`
	Abstract          string   `json:"abstract"`
	Year              int      `json:"year"`
	BestOALocation    string   `json:"best_oa_location"`
	ReferencedWorks   []string `json:"referenced_works"`
	RelatedWorks      []string `json:"related_works"`
	Status            string   `json:"status"`
	ModeratedByUserID int64    `json:"moderated_by_user_id"`
	ModerationComment string   `json:"moderation_comment"`
	ApprovedPaperID   int64    `json:"approved_paper_id"`
	CreatedAt         string   `json:"created_at"`
	UpdatedAt         string   `json:"updated_at"`
	SubmittedAt       string   `json:"submitted_at"`
	ModeratedAt       string   `json:"moderated_at"`
}

type SubmissionListResponse struct {
	Items  []SubmissionRecord `json:"items"`
	Total  int64              `json:"total"`
	Limit  int64              `json:"limit"`
	Offset int64              `json:"offset"`
}

type ModerateSubmissionRequest struct {
	Action  string `json:"action"`
	Comment string `json:"comment"`
}
