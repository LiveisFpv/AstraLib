package service

import (
	pb "VKR_gateway_service/gen/go"
	"VKR_gateway_service/internal/domain"
	"VKR_gateway_service/internal/transport/rpc"
	"context"
	"errors"

	"github.com/sirupsen/logrus"
)

var (
	ErrAddPaperRPC = errors.New("RPC Failed to add paper, bad status code")
)

type PaperService interface {
	AddPaper(ctx context.Context, paper *domain.Paper, reference []*domain.ReferencedPaper, relate []*domain.RelatedPaper) (*domain.Paper, error)
}

type paperService struct {
	SemanticClient rpc.SemanticClient
	logger         *logrus.Logger
}

func NewPaperService(SemanticClient rpc.SemanticClient, logger *logrus.Logger) PaperService {
	return &paperService{
		SemanticClient: SemanticClient,
		logger:         logger,
	}
}

func (p *paperService) AddPaper(ctx context.Context, paper *domain.Paper, reference []*domain.ReferencedPaper, relate []*domain.RelatedPaper) (*domain.Paper, error) {
	ReferencedWorks := make([]*pb.ReferencedWorks, 0, len(reference))
	for _, p := range reference {
		ReferencedWorks = append(ReferencedWorks, &pb.ReferencedWorks{
			ID: p.Id,
		})
	}
	RelatedWorks := make([]*pb.RelatedWorks, 0, len(relate))
	for _, p := range relate {
		RelatedWorks = append(RelatedWorks, &pb.RelatedWorks{
			ID: p.Id,
		})
	}
	req := &pb.AddRequest{
		ID:              paper.Id,
		Title:           paper.Title,
		Abstract:        paper.Abstract,
		Year:            int64(paper.Year),
		BestOaLocation:  paper.Best_oa_location,
		ReferencedWorks: ReferencedWorks,
		RelatedWorks:    RelatedWorks,
	}
	paper_r, err := p.SemanticClient.AddPaper(ctx, req)
	if err != nil {
		p.logger.WithError(err).Error("AI AddPaper RPC failed")
		return nil, err
	}
	return &domain.Paper{
		Id:               paper_r.ID,
		Title:            paper_r.Title,
		Abstract:         paper_r.Abstract,
		Year:             int(paper_r.Year),
		Best_oa_location: paper_r.BestOaLocation,
		State:            paper_r.State,
		ReferencedWorks:  cloneStringSlice(paper_r.GetReferencedWorks()),
		RelatedWorks:     cloneStringSlice(paper_r.GetRelatedWorks()),
		CitedByCount:     int(paper_r.GetCitedByCount()),
		Authors:          cloneStringSlice(paper_r.GetAuthors()),
		Institutions:     cloneStringSlice(paper_r.GetInstitutions()),
		Identifiers:      mapPaperIdentifiers(paper_r.GetIdentifiers()),
	}, err
}
