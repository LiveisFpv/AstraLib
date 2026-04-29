package service

import (
	pb "VKR_gateway_service/gen/go"
	"VKR_gateway_service/internal/domain"
)

func mapChat(chat *pb.Chat) *domain.Chat {
	if chat == nil {
		return &domain.Chat{}
	}
	return &domain.Chat{
		ChatId:    chat.GetChatId(),
		UserId:    chat.GetUserId(),
		UpdatedAt: chat.GetUpdatedAt(),
		Title:     chat.GetTitle(),
	}
}

func mapChatPapers(papers []*pb.ChatPaperResponse) []*domain.ChatPaper {
	out := make([]*domain.ChatPaper, 0, len(papers))
	for _, p := range papers {
		out = append(out, &domain.ChatPaper{
			Id:               p.ID,
			Title:            p.Title,
			Abstract:         p.Abstract,
			Year:             int(p.Year),
			Best_oa_location: p.BestOaLocation,
			State:            p.State,
			ReferencedWorks:  cloneStringSlice(p.GetReferencedWorks()),
			RelatedWorks:     cloneStringSlice(p.GetRelatedWorks()),
			CitedByCount:     int(p.GetCitedByCount()),
			Authors:          cloneStringSlice(p.GetAuthors()),
			Institutions:     cloneStringSlice(p.GetInstitutions()),
			Identifiers:      mapPaperIdentifiers(p.GetIdentifiers()),
			Score:            p.Score,
		})
	}
	return out
}

func cloneStringSlice(values []string) []string {
	return append([]string{}, values...)
}

func mapPaperIdentifiers(identifiers []*pb.PaperIdentifier) []domain.PaperIdentifier {
	out := make([]domain.PaperIdentifier, 0, len(identifiers))
	for _, identifier := range identifiers {
		out = append(out, domain.PaperIdentifier{
			Type:  identifier.GetType(),
			Value: identifier.GetValue(),
		})
	}
	return out
}
