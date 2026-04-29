package presenters

type CreateChatRequest struct {
	UserId int64  `json:"user_id"`
	Title  string `json:"title"`
}

type Chat struct {
	ChatId    int64  `json:"chat_id"`
	UserId    int64  `json:"user_id"`
	UpdatedAt string `json:"updated_at"`
	Title     string `json:"title"`
}

type ChatResponse struct {
	ChatId    int64  `json:"chat_id"`
	UserId    int64  `json:"user_id"`
	UpdatedAt string `json:"updated_at"`
	Title     string `json:"title"`
}

type ChatsResponse struct {
	Chats []ChatResponse `json:"chats"`
}

type ChatHistoryCreateRequest struct {
	Text string `json:"text" binding:"required"`
}

type ChatPaper struct {
	Id               string            `json:"id"`
	Title            string            `json:"title"`
	Abstract         string            `json:"abstract"`
	Year             int               `json:"year"`
	Best_oa_location string            `json:"best_oa_location"`
	State            string            `json:"state"`
	ReferencedWorks  []string          `json:"referenced_works"`
	RelatedWorks     []string          `json:"related_works"`
	CitedByCount     int               `json:"cited_by_count"`
	Authors          []string          `json:"authors"`
	Institutions     []string          `json:"institutions"`
	Identifiers      []PaperIdentifier `json:"identifiers"`
	Score            float64           `json:"score"`
}

type ChatHistoryMessage struct {
	SearchQuery string      `json:"search_query"`
	CreatedAt   string      `json:"created_at"`
	Papers      []ChatPaper `json:"papers"`
}

type ChatHistoryResponse struct {
	ChatMessages []ChatHistoryMessage `json:"chat_messages"`
}
