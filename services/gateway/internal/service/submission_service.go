package service

import (
	pb "VKR_gateway_service/gen/go"
	"VKR_gateway_service/internal/domain"
	"VKR_gateway_service/internal/transport/rpc"
	"context"
	"errors"
	"strconv"
	"strings"

	"github.com/sirupsen/logrus"
	"google.golang.org/grpc/metadata"
)

var (
	ErrSubmissionRPC = errors.New("RPC error failed to process submission request")
)

type SubmissionService interface {
	Create(ctx context.Context, actor domain.SubmissionActor, input *domain.SubmissionUpsertInput) (*domain.Submission, error)
	Update(ctx context.Context, actor domain.SubmissionActor, submissionID int64, input *domain.SubmissionUpsertInput) (*domain.Submission, error)
	Delete(ctx context.Context, actor domain.SubmissionActor, submissionID int64) error
	Get(ctx context.Context, actor domain.SubmissionActor, submissionID int64) (*domain.Submission, error)
	List(ctx context.Context, actor domain.SubmissionActor, statuses []string, limit, offset int64) (*domain.SubmissionList, error)
	Submit(ctx context.Context, actor domain.SubmissionActor, submissionID int64) (*domain.Submission, error)
	ListModeration(ctx context.Context, actor domain.SubmissionActor, statuses []string, limit, offset int64) (*domain.SubmissionList, error)
	GetModeration(ctx context.Context, actor domain.SubmissionActor, submissionID int64) (*domain.Submission, error)
	UpdateModeration(ctx context.Context, actor domain.SubmissionActor, submissionID int64, input *domain.SubmissionUpsertInput) (*domain.Submission, error)
	Moderate(ctx context.Context, actor domain.SubmissionActor, submissionID int64, decision *domain.ModerationDecision) (*domain.Submission, error)
}

type submissionService struct {
	SemanticClient rpc.SemanticClient
	logger         *logrus.Logger
}

func NewSubmissionService(semanticClient rpc.SemanticClient, logger *logrus.Logger) SubmissionService {
	return &submissionService{
		SemanticClient: semanticClient,
		logger:         logger,
	}
}

func (s *submissionService) Create(ctx context.Context, actor domain.SubmissionActor, input *domain.SubmissionUpsertInput) (*domain.Submission, error) {
	req := &pb.CreateMySubmissionRequest{
		SourceIdentifier: input.SourceIdentifier,
		Title:            input.Title,
		Abstract:         input.Abstract,
		Year:             int64(input.Year),
		BestOaLocation:   input.BestOALocation,
		ReferencedWorks:  append([]string(nil), input.ReferencedWorks...),
		RelatedWorks:     append([]string(nil), input.RelatedWorks...),
	}
	resp, err := s.SemanticClient.CreateMySubmission(withSubmissionMetadata(ctx, actor), req)
	if err != nil {
		s.logger.WithError(err).WithField("user_id", actor.UserID).Error("semantic CreateMySubmission RPC failed")
		return nil, err
	}
	return mapSubmission(resp.GetSubmission()), nil
}

func (s *submissionService) Update(ctx context.Context, actor domain.SubmissionActor, submissionID int64, input *domain.SubmissionUpsertInput) (*domain.Submission, error) {
	req := &pb.UpdateMySubmissionRequest{
		SubmissionId:     submissionID,
		SourceIdentifier: input.SourceIdentifier,
		Title:            input.Title,
		Abstract:         input.Abstract,
		Year:             int64(input.Year),
		BestOaLocation:   input.BestOALocation,
		ReferencedWorks:  append([]string(nil), input.ReferencedWorks...),
		RelatedWorks:     append([]string(nil), input.RelatedWorks...),
	}
	resp, err := s.SemanticClient.UpdateMySubmission(withSubmissionMetadata(ctx, actor), req)
	if err != nil {
		s.logger.WithError(err).WithFields(logrus.Fields{
			"user_id":       actor.UserID,
			"submission_id": submissionID,
		}).Error("semantic UpdateMySubmission RPC failed")
		return nil, err
	}
	return mapSubmission(resp.GetSubmission()), nil
}

func (s *submissionService) Delete(ctx context.Context, actor domain.SubmissionActor, submissionID int64) error {
	req := &pb.DeleteMySubmissionRequest{SubmissionId: submissionID}
	_, err := s.SemanticClient.DeleteMySubmission(withSubmissionMetadata(ctx, actor), req)
	if err != nil {
		s.logger.WithError(err).WithFields(logrus.Fields{
			"user_id":       actor.UserID,
			"submission_id": submissionID,
		}).Error("semantic DeleteMySubmission RPC failed")
	}
	return err
}

func (s *submissionService) Get(ctx context.Context, actor domain.SubmissionActor, submissionID int64) (*domain.Submission, error) {
	req := &pb.GetMySubmissionRequest{SubmissionId: submissionID}
	resp, err := s.SemanticClient.GetMySubmission(withSubmissionMetadata(ctx, actor), req)
	if err != nil {
		s.logger.WithError(err).WithFields(logrus.Fields{
			"user_id":       actor.UserID,
			"submission_id": submissionID,
		}).Error("semantic GetMySubmission RPC failed")
		return nil, err
	}
	return mapSubmission(resp.GetSubmission()), nil
}

func (s *submissionService) List(ctx context.Context, actor domain.SubmissionActor, statuses []string, limit, offset int64) (*domain.SubmissionList, error) {
	req := &pb.ListMySubmissionsRequest{
		Statuses: append([]string(nil), statuses...),
		Limit:    limit,
		Offset:   offset,
	}
	resp, err := s.SemanticClient.ListMySubmissions(withSubmissionMetadata(ctx, actor), req)
	if err != nil {
		s.logger.WithError(err).WithField("user_id", actor.UserID).Error("semantic ListMySubmissions RPC failed")
		return nil, err
	}
	return mapSubmissionList(resp), nil
}

func (s *submissionService) Submit(ctx context.Context, actor domain.SubmissionActor, submissionID int64) (*domain.Submission, error) {
	req := &pb.SubmitMySubmissionRequest{SubmissionId: submissionID}
	resp, err := s.SemanticClient.SubmitMySubmission(withSubmissionMetadata(ctx, actor), req)
	if err != nil {
		s.logger.WithError(err).WithFields(logrus.Fields{
			"user_id":       actor.UserID,
			"submission_id": submissionID,
		}).Error("semantic SubmitMySubmission RPC failed")
		return nil, err
	}
	return mapSubmission(resp.GetSubmission()), nil
}

func (s *submissionService) ListModeration(ctx context.Context, actor domain.SubmissionActor, statuses []string, limit, offset int64) (*domain.SubmissionList, error) {
	req := &pb.ListModerationQueueRequest{
		Statuses: append([]string(nil), statuses...),
		Limit:    limit,
		Offset:   offset,
	}
	resp, err := s.SemanticClient.ListModerationQueue(withSubmissionMetadata(ctx, actor), req)
	if err != nil {
		s.logger.WithError(err).WithField("user_id", actor.UserID).Error("semantic ListModerationQueue RPC failed")
		return nil, err
	}
	return mapSubmissionList(resp), nil
}

func (s *submissionService) GetModeration(ctx context.Context, actor domain.SubmissionActor, submissionID int64) (*domain.Submission, error) {
	req := &pb.GetModerationSubmissionRequest{SubmissionId: submissionID}
	resp, err := s.SemanticClient.GetModerationSubmission(withSubmissionMetadata(ctx, actor), req)
	if err != nil {
		s.logger.WithError(err).WithFields(logrus.Fields{
			"user_id":       actor.UserID,
			"submission_id": submissionID,
		}).Error("semantic GetModerationSubmission RPC failed")
		return nil, err
	}
	return mapSubmission(resp.GetSubmission()), nil
}

func (s *submissionService) UpdateModeration(ctx context.Context, actor domain.SubmissionActor, submissionID int64, input *domain.SubmissionUpsertInput) (*domain.Submission, error) {
	req := &pb.UpdateModerationSubmissionRequest{
		SubmissionId:     submissionID,
		SourceIdentifier: input.SourceIdentifier,
		Title:            input.Title,
		Abstract:         input.Abstract,
		Year:             int64(input.Year),
		BestOaLocation:   input.BestOALocation,
		ReferencedWorks:  append([]string(nil), input.ReferencedWorks...),
		RelatedWorks:     append([]string(nil), input.RelatedWorks...),
	}
	resp, err := s.SemanticClient.UpdateModerationSubmission(withSubmissionMetadata(ctx, actor), req)
	if err != nil {
		s.logger.WithError(err).WithFields(logrus.Fields{
			"user_id":       actor.UserID,
			"submission_id": submissionID,
		}).Error("semantic UpdateModerationSubmission RPC failed")
		return nil, err
	}
	return mapSubmission(resp.GetSubmission()), nil
}

func (s *submissionService) Moderate(ctx context.Context, actor domain.SubmissionActor, submissionID int64, decision *domain.ModerationDecision) (*domain.Submission, error) {
	req := &pb.ModerateSubmissionRequest{
		SubmissionId: submissionID,
		Action:       decision.Action,
		Comment:      decision.Comment,
	}
	resp, err := s.SemanticClient.ModerateSubmission(withSubmissionMetadata(ctx, actor), req)
	if err != nil {
		s.logger.WithError(err).WithFields(logrus.Fields{
			"user_id":       actor.UserID,
			"submission_id": submissionID,
			"action":        decision.Action,
		}).Error("semantic ModerateSubmission RPC failed")
		return nil, err
	}
	return mapSubmission(resp.GetSubmission()), nil
}

func withSubmissionMetadata(ctx context.Context, actor domain.SubmissionActor) context.Context {
	pairs := []string{"x-user-id", strconv.FormatInt(actor.UserID, 10)}
	for _, role := range normalizeMetadataRoles(actor.Roles) {
		pairs = append(pairs, "x-user-role", role)
	}
	return metadata.AppendToOutgoingContext(ctx, pairs...)
}

func normalizeMetadataRoles(raw []string) []string {
	normalized := make([]string, 0, len(raw)+1)
	seen := make(map[string]struct{}, len(raw)+1)
	hasAdmin := false
	hasModerator := false
	for _, role := range raw {
		role = strings.TrimSpace(strings.ToLower(role))
		if role == "" {
			continue
		}
		if _, ok := seen[role]; ok {
			continue
		}
		seen[role] = struct{}{}
		normalized = append(normalized, role)
		if role == "admin" {
			hasAdmin = true
		}
		if role == "moderator" {
			hasModerator = true
		}
	}
	if hasAdmin && !hasModerator {
		normalized = append(normalized, "moderator")
	}
	return normalized
}

func mapSubmission(record *pb.SubmissionRecord) *domain.Submission {
	if record == nil {
		return &domain.Submission{}
	}
	return &domain.Submission{
		SubmissionID:      record.GetSubmissionId(),
		CreatedByUserID:   record.GetCreatedByUserId(),
		SourceIdentifier:  record.GetSourceIdentifier(),
		Title:             record.GetTitle(),
		Abstract:          record.GetAbstract(),
		Year:              int(record.GetYear()),
		BestOALocation:    record.GetBestOaLocation(),
		ReferencedWorks:   append([]string(nil), record.GetReferencedWorks()...),
		RelatedWorks:      append([]string(nil), record.GetRelatedWorks()...),
		Status:            record.GetStatus(),
		ModeratedByUserID: record.GetModeratedByUserId(),
		ModerationComment: record.GetModerationComment(),
		ApprovedPaperID:   record.GetApprovedPaperId(),
		CreatedAt:         record.GetCreatedAt(),
		UpdatedAt:         record.GetUpdatedAt(),
		SubmittedAt:       record.GetSubmittedAt(),
		ModeratedAt:       record.GetModeratedAt(),
	}
}

func mapSubmissionList(resp *pb.SubmissionListResponse) *domain.SubmissionList {
	if resp == nil {
		return &domain.SubmissionList{}
	}
	items := make([]*domain.Submission, 0, len(resp.GetItems()))
	for _, item := range resp.GetItems() {
		items = append(items, mapSubmission(item))
	}
	return &domain.SubmissionList{
		Items:  items,
		Total:  resp.GetTotal(),
		Limit:  resp.GetLimit(),
		Offset: resp.GetOffset(),
	}
}
