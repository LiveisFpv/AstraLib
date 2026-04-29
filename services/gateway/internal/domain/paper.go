package domain

type Paper struct {
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
}

type PaperIdentifier struct {
	Type  string
	Value string
}

type ReferencedPaper struct {
	Id string `json:"id"`
}

type RelatedPaper struct {
	Id string `json:"id"`
}
