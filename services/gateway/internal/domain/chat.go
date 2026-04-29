package domain

type Chat struct {
	ChatId    int64  `json:"chat_id"`
	UserId    int64  `json:"user_id"`
	UpdatedAt string `json:"updated_at"`
	Title     string `json:"title"`
}

type ChatHistoryMessage struct {
	SearchQuery string       `json:"search_query"`
	CreatedAt   string       `json:"created_at"`
	Papers      []*ChatPaper `json:"papers"`
}

type ChatPaper struct {
	Id               string `json:"id"`
	Title            string `json:"title"`
	Abstract         string `json:"abstract"`
	Year             int    `json:"year"`
	Best_oa_location string `json:"best_oa_location"`
	State            string `json:"state"`
	ReferencedWorks  []string
	RelatedWorks     []string
	CitedByCount     int
	Authors          []string
	Institutions     []string
	Identifiers      []PaperIdentifier
	Score            float64
}
