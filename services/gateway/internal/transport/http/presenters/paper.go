package presenters

type AddPaperRequest struct {
	Id               string            `json:"id"`
	Title            string            `json:"title"`
	Abstract         string            `json:"abstract"`
	Year             int               `json:"year"`
	Best_oa_location string            `json:"best_oa_location"`
	ReferencedPapers []ReferencedPaper `json:"referenced_paper"`
	RelatedPaper     []RelatedPaper    `json:"related_paper"`
}

type Paper struct {
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
}

type PaperIdentifier struct {
	Type  string `json:"type"`
	Value string `json:"value"`
}

type ReferencedPaper struct {
	Id string `json:"id"`
}

type RelatedPaper struct {
	Id string `json:"id"`
}
