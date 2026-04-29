package handlers

import (
	"VKR_gateway_service/internal/domain"
	"VKR_gateway_service/internal/transport/http/presenters"
	"fmt"
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

func mapGRPCToHTTP(err error) int {
	s, _ := status.FromError(err)
	c := s.Code()
	switch c {
	case codes.InvalidArgument:
		return http.StatusBadRequest
	case codes.AlreadyExists, codes.FailedPrecondition:
		return http.StatusConflict
	case codes.NotFound:
		return http.StatusNotFound
	case codes.DeadlineExceeded:
		return http.StatusGatewayTimeout
	case codes.Unavailable:
		return http.StatusBadGateway
	case codes.Unauthenticated:
		return http.StatusUnauthorized
	case codes.PermissionDenied:
		return http.StatusForbidden
	default:
		return http.StatusBadGateway
	}
}

func parsePathInt64(ctx *gin.Context, name string) (int64, error) {
	raw := ctx.Param(name)
	if raw == "" {
		return 0, fmt.Errorf("%s path param is required", name)
	}
	return parsePositiveInt64(raw, name)
}

func parsePositiveInt64(raw, field string) (int64, error) {
	val, err := strconv.ParseInt(raw, 10, 64)
	if err != nil || val <= 0 {
		return 0, fmt.Errorf("%s must be a positive integer", field)
	}
	return val, nil
}

// function that search userID in context and compare it with given ID
func resolveUserID(ctx *gin.Context, userID int64) (int64, int, error) {
	authID, ok := authUserID(ctx)
	if userID > 0 {
		if ok && authID != userID {
			return 0, http.StatusForbidden, fmt.Errorf("user_id does not match token")
		}
		return userID, 0, nil
	}
	if ok {
		return authID, 0, nil
	}
	return 0, http.StatusUnauthorized, fmt.Errorf("user_id is required")
}

// function that try to find userID in context and parse it
func authUserID(ctx *gin.Context) (int64, bool) {
	val, ok := ctx.Get("user_id")
	if !ok {
		return 0, false
	}
	switch v := val.(type) {
	case int64:
		return v, true
	case int:
		return int64(v), true
	case float64:
		return int64(v), true
	case string:
		id, err := strconv.ParseInt(v, 10, 64)
		if err != nil {
			return 0, false
		}
		return id, true
	default:
		return 0, false
	}
}

func authRoles(ctx *gin.Context) []string {
	val, ok := ctx.Get("roles")
	if !ok {
		return nil
	}
	switch typed := val.(type) {
	case []string:
		return append([]string(nil), typed...)
	case []any:
		roles := make([]string, 0, len(typed))
		for _, raw := range typed {
			role := strings.TrimSpace(strings.ToUpper(fmt.Sprint(raw)))
			if role != "" {
				roles = append(roles, role)
			}
		}
		return roles
	default:
		return nil
	}
}

func parseQueryInt64(ctx *gin.Context, name string, defaultValue int64) (int64, error) {
	raw := strings.TrimSpace(ctx.Query(name))
	if raw == "" {
		return defaultValue, nil
	}
	val, err := strconv.ParseInt(raw, 10, 64)
	if err != nil || val < 0 {
		return 0, fmt.Errorf("%s must be a non-negative integer", name)
	}
	return val, nil
}

func parseStatusesQuery(ctx *gin.Context) []string {
	values := make([]string, 0)
	values = append(values, ctx.QueryArray("status")...)
	values = append(values, ctx.QueryArray("statuses")...)
	if raw := strings.TrimSpace(ctx.Query("status")); raw != "" {
		values = append(values, strings.Split(raw, ",")...)
	}
	if raw := strings.TrimSpace(ctx.Query("statuses")); raw != "" {
		values = append(values, strings.Split(raw, ",")...)
	}

	seen := make(map[string]struct{}, len(values))
	out := make([]string, 0, len(values))
	for _, value := range values {
		status := strings.TrimSpace(strings.ToLower(value))
		if status == "" {
			continue
		}
		if _, ok := seen[status]; ok {
			continue
		}
		seen[status] = struct{}{}
		out = append(out, status)
	}
	return out
}

func mapChat(chat *domain.Chat) presenters.ChatResponse {
	if chat == nil {
		return presenters.ChatResponse{}
	}
	return presenters.ChatResponse{
		ChatId:    chat.ChatId,
		UserId:    chat.UserId,
		UpdatedAt: chat.UpdatedAt,
		Title:     chat.Title,
	}
}

func mapPapers(papers []*domain.Paper) []presenters.Paper {
	out := make([]presenters.Paper, 0, len(papers))
	for _, p := range papers {
		out = append(out, presenters.Paper{
			Id:               p.Id,
			Title:            p.Title,
			Abstract:         p.Abstract,
			Year:             p.Year,
			Best_oa_location: p.Best_oa_location,
			State:            p.State,
			ReferencedWorks:  cloneStringSlice(p.ReferencedWorks),
			RelatedWorks:     cloneStringSlice(p.RelatedWorks),
			CitedByCount:     p.CitedByCount,
			Authors:          cloneStringSlice(p.Authors),
			Institutions:     cloneStringSlice(p.Institutions),
			Identifiers:      mapPaperIdentifiers(p.Identifiers),
		})
	}
	return out
}

func cloneStringSlice(values []string) []string {
	return append([]string{}, values...)
}

func mapPaperIdentifiers(identifiers []domain.PaperIdentifier) []presenters.PaperIdentifier {
	out := make([]presenters.PaperIdentifier, 0, len(identifiers))
	for _, identifier := range identifiers {
		out = append(out, presenters.PaperIdentifier{
			Type:  identifier.Type,
			Value: identifier.Value,
		})
	}
	return out
}

func mapSubmission(submission *domain.Submission) presenters.SubmissionRecord {
	if submission == nil {
		return presenters.SubmissionRecord{}
	}
	return presenters.SubmissionRecord{
		SubmissionID:      submission.SubmissionID,
		CreatedByUserID:   submission.CreatedByUserID,
		SourceIdentifier:  submission.SourceIdentifier,
		Title:             submission.Title,
		Abstract:          submission.Abstract,
		Year:              submission.Year,
		BestOALocation:    submission.BestOALocation,
		ReferencedWorks:   append([]string(nil), submission.ReferencedWorks...),
		RelatedWorks:      append([]string(nil), submission.RelatedWorks...),
		Status:            submission.Status,
		ModeratedByUserID: submission.ModeratedByUserID,
		ModerationComment: submission.ModerationComment,
		ApprovedPaperID:   submission.ApprovedPaperID,
		CreatedAt:         submission.CreatedAt,
		UpdatedAt:         submission.UpdatedAt,
		SubmittedAt:       submission.SubmittedAt,
		ModeratedAt:       submission.ModeratedAt,
	}
}

func mapSubmissionList(list *domain.SubmissionList) presenters.SubmissionListResponse {
	if list == nil {
		return presenters.SubmissionListResponse{}
	}
	items := make([]presenters.SubmissionRecord, 0, len(list.Items))
	for _, item := range list.Items {
		items = append(items, mapSubmission(item))
	}
	return presenters.SubmissionListResponse{
		Items:  items,
		Total:  list.Total,
		Limit:  list.Limit,
		Offset: list.Offset,
	}
}
