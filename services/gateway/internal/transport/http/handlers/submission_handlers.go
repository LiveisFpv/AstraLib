package handlers

import (
	"VKR_gateway_service/internal/app"
	"VKR_gateway_service/internal/domain"
	"VKR_gateway_service/internal/transport/http/presenters"
	"net/http"

	"github.com/gin-gonic/gin"
)

// CreateSubmission
// @Summary Create submission draft
// @Description Create a new author submission draft
// @Tags submissions
// @Accept json
// @Produce json
// @Param data body presenters.SubmissionUpsertRequest true "Submission payload"
// @Success 200 {object} presenters.SubmissionResponse
// @Failure 400 {object} presenters.ErrorResponse
// @Failure 401 {object} presenters.ErrorResponse
// @Failure 403 {object} presenters.ErrorResponse
// @Failure 404 {object} presenters.ErrorResponse
// @Failure 409 {object} presenters.ErrorResponse
// @Failure 502 {object} presenters.ErrorResponse
// @Router /submissions [post]
func CreateSubmission(ctx *gin.Context, a *app.App) {
	var in presenters.SubmissionUpsertRequest
	if err := ctx.ShouldBindJSON(&in); err != nil {
		ctx.JSON(http.StatusBadRequest, presenters.Error(err))
		return
	}
	actor, statusCode, err := resolveSubmissionActor(ctx)
	if err != nil {
		ctx.JSON(statusCode, presenters.Error(err))
		return
	}
	submission, err := a.SubmissionService.Create(ctx.Request.Context(), actor, mapSubmissionInput(&in))
	if err != nil {
		ctx.JSON(mapGRPCToHTTP(err), presenters.Error(err))
		return
	}
	ctx.JSON(http.StatusOK, presenters.SubmissionResponse{Submission: mapSubmission(submission)})
}

// ListMySubmissions
// @Summary List my submissions
// @Description List submissions created by the authenticated user
// @Tags submissions
// @Produce json
// @Param status query []string false "Submission statuses"
// @Param limit query int false "Page size"
// @Param offset query int false "Offset"
// @Success 200 {object} presenters.SubmissionListResponse
// @Failure 400 {object} presenters.ErrorResponse
// @Failure 401 {object} presenters.ErrorResponse
// @Failure 403 {object} presenters.ErrorResponse
// @Failure 502 {object} presenters.ErrorResponse
// @Router /submissions [get]
func ListMySubmissions(ctx *gin.Context, a *app.App) {
	actor, statusCode, err := resolveSubmissionActor(ctx)
	if err != nil {
		ctx.JSON(statusCode, presenters.Error(err))
		return
	}
	limit, err := parseQueryInt64(ctx, "limit", 20)
	if err != nil {
		ctx.JSON(http.StatusBadRequest, presenters.Error(err))
		return
	}
	offset, err := parseQueryInt64(ctx, "offset", 0)
	if err != nil {
		ctx.JSON(http.StatusBadRequest, presenters.Error(err))
		return
	}
	result, err := a.SubmissionService.List(
		ctx.Request.Context(),
		actor,
		parseStatusesQuery(ctx),
		limit,
		offset,
	)
	if err != nil {
		ctx.JSON(mapGRPCToHTTP(err), presenters.Error(err))
		return
	}
	ctx.JSON(http.StatusOK, mapSubmissionList(result))
}

// GetMySubmission
// @Summary Get my submission
// @Description Get a single submission created by the authenticated user
// @Tags submissions
// @Produce json
// @Param submission_id path int true "Submission ID"
// @Success 200 {object} presenters.SubmissionResponse
// @Failure 400 {object} presenters.ErrorResponse
// @Failure 401 {object} presenters.ErrorResponse
// @Failure 403 {object} presenters.ErrorResponse
// @Failure 404 {object} presenters.ErrorResponse
// @Failure 502 {object} presenters.ErrorResponse
// @Router /submissions/{submission_id} [get]
func GetMySubmission(ctx *gin.Context, a *app.App) {
	submissionID, err := parsePathInt64(ctx, "submission_id")
	if err != nil {
		ctx.JSON(http.StatusBadRequest, presenters.Error(err))
		return
	}
	actor, statusCode, err := resolveSubmissionActor(ctx)
	if err != nil {
		ctx.JSON(statusCode, presenters.Error(err))
		return
	}
	submission, err := a.SubmissionService.Get(ctx.Request.Context(), actor, submissionID)
	if err != nil {
		ctx.JSON(mapGRPCToHTTP(err), presenters.Error(err))
		return
	}
	ctx.JSON(http.StatusOK, presenters.SubmissionResponse{Submission: mapSubmission(submission)})
}

// UpdateMySubmission
// @Summary Update my submission
// @Description Replace the current staged data of an authenticated user's submission
// @Tags submissions
// @Accept json
// @Produce json
// @Param submission_id path int true "Submission ID"
// @Param data body presenters.SubmissionUpsertRequest true "Submission payload"
// @Success 200 {object} presenters.SubmissionResponse
// @Failure 400 {object} presenters.ErrorResponse
// @Failure 401 {object} presenters.ErrorResponse
// @Failure 403 {object} presenters.ErrorResponse
// @Failure 404 {object} presenters.ErrorResponse
// @Failure 409 {object} presenters.ErrorResponse
// @Failure 502 {object} presenters.ErrorResponse
// @Router /submissions/{submission_id} [put]
func UpdateMySubmission(ctx *gin.Context, a *app.App) {
	submissionID, err := parsePathInt64(ctx, "submission_id")
	if err != nil {
		ctx.JSON(http.StatusBadRequest, presenters.Error(err))
		return
	}
	var in presenters.SubmissionUpsertRequest
	if err := ctx.ShouldBindJSON(&in); err != nil {
		ctx.JSON(http.StatusBadRequest, presenters.Error(err))
		return
	}
	actor, statusCode, err := resolveSubmissionActor(ctx)
	if err != nil {
		ctx.JSON(statusCode, presenters.Error(err))
		return
	}
	submission, err := a.SubmissionService.Update(ctx.Request.Context(), actor, submissionID, mapSubmissionInput(&in))
	if err != nil {
		ctx.JSON(mapGRPCToHTTP(err), presenters.Error(err))
		return
	}
	ctx.JSON(http.StatusOK, presenters.SubmissionResponse{Submission: mapSubmission(submission)})
}

// DeleteMySubmission
// @Summary Delete my submission
// @Description Delete a draft or rejected submission of the authenticated user
// @Tags submissions
// @Produce json
// @Param submission_id path int true "Submission ID"
// @Success 204
// @Failure 400 {object} presenters.ErrorResponse
// @Failure 401 {object} presenters.ErrorResponse
// @Failure 403 {object} presenters.ErrorResponse
// @Failure 404 {object} presenters.ErrorResponse
// @Failure 409 {object} presenters.ErrorResponse
// @Failure 502 {object} presenters.ErrorResponse
// @Router /submissions/{submission_id} [delete]
func DeleteMySubmission(ctx *gin.Context, a *app.App) {
	submissionID, err := parsePathInt64(ctx, "submission_id")
	if err != nil {
		ctx.JSON(http.StatusBadRequest, presenters.Error(err))
		return
	}
	actor, statusCode, err := resolveSubmissionActor(ctx)
	if err != nil {
		ctx.JSON(statusCode, presenters.Error(err))
		return
	}
	if err := a.SubmissionService.Delete(ctx.Request.Context(), actor, submissionID); err != nil {
		ctx.JSON(mapGRPCToHTTP(err), presenters.Error(err))
		return
	}
	ctx.Status(http.StatusNoContent)
}

// SubmitMySubmission
// @Summary Submit draft for review
// @Description Move a submission to moderation queue
// @Tags submissions
// @Produce json
// @Param submission_id path int true "Submission ID"
// @Success 200 {object} presenters.SubmissionResponse
// @Failure 400 {object} presenters.ErrorResponse
// @Failure 401 {object} presenters.ErrorResponse
// @Failure 403 {object} presenters.ErrorResponse
// @Failure 404 {object} presenters.ErrorResponse
// @Failure 409 {object} presenters.ErrorResponse
// @Failure 502 {object} presenters.ErrorResponse
// @Router /submissions/{submission_id}/submit [post]
func SubmitMySubmission(ctx *gin.Context, a *app.App) {
	submissionID, err := parsePathInt64(ctx, "submission_id")
	if err != nil {
		ctx.JSON(http.StatusBadRequest, presenters.Error(err))
		return
	}
	actor, statusCode, err := resolveSubmissionActor(ctx)
	if err != nil {
		ctx.JSON(statusCode, presenters.Error(err))
		return
	}
	submission, err := a.SubmissionService.Submit(ctx.Request.Context(), actor, submissionID)
	if err != nil {
		ctx.JSON(mapGRPCToHTTP(err), presenters.Error(err))
		return
	}
	ctx.JSON(http.StatusOK, presenters.SubmissionResponse{Submission: mapSubmission(submission)})
}

// ListModerationSubmissions
// @Summary List moderation queue
// @Description List submissions for moderation
// @Tags moderation
// @Produce json
// @Param status query []string false "Submission statuses"
// @Param limit query int false "Page size"
// @Param offset query int false "Offset"
// @Success 200 {object} presenters.SubmissionListResponse
// @Failure 400 {object} presenters.ErrorResponse
// @Failure 401 {object} presenters.ErrorResponse
// @Failure 403 {object} presenters.ErrorResponse
// @Failure 502 {object} presenters.ErrorResponse
// @Router /moderation/submissions [get]
func ListModerationSubmissions(ctx *gin.Context, a *app.App) {
	actor, statusCode, err := resolveSubmissionActor(ctx)
	if err != nil {
		ctx.JSON(statusCode, presenters.Error(err))
		return
	}
	limit, err := parseQueryInt64(ctx, "limit", 20)
	if err != nil {
		ctx.JSON(http.StatusBadRequest, presenters.Error(err))
		return
	}
	offset, err := parseQueryInt64(ctx, "offset", 0)
	if err != nil {
		ctx.JSON(http.StatusBadRequest, presenters.Error(err))
		return
	}
	result, err := a.SubmissionService.ListModeration(
		ctx.Request.Context(),
		actor,
		parseStatusesQuery(ctx),
		limit,
		offset,
	)
	if err != nil {
		ctx.JSON(mapGRPCToHTTP(err), presenters.Error(err))
		return
	}
	ctx.JSON(http.StatusOK, mapSubmissionList(result))
}

// GetModerationSubmission
// @Summary Get moderation submission
// @Description Get a single submission for moderation
// @Tags moderation
// @Produce json
// @Param submission_id path int true "Submission ID"
// @Success 200 {object} presenters.SubmissionResponse
// @Failure 400 {object} presenters.ErrorResponse
// @Failure 401 {object} presenters.ErrorResponse
// @Failure 403 {object} presenters.ErrorResponse
// @Failure 404 {object} presenters.ErrorResponse
// @Failure 502 {object} presenters.ErrorResponse
// @Router /moderation/submissions/{submission_id} [get]
func GetModerationSubmission(ctx *gin.Context, a *app.App) {
	submissionID, err := parsePathInt64(ctx, "submission_id")
	if err != nil {
		ctx.JSON(http.StatusBadRequest, presenters.Error(err))
		return
	}
	actor, statusCode, err := resolveSubmissionActor(ctx)
	if err != nil {
		ctx.JSON(statusCode, presenters.Error(err))
		return
	}
	submission, err := a.SubmissionService.GetModeration(ctx.Request.Context(), actor, submissionID)
	if err != nil {
		ctx.JSON(mapGRPCToHTTP(err), presenters.Error(err))
		return
	}
	ctx.JSON(http.StatusOK, presenters.SubmissionResponse{Submission: mapSubmission(submission)})
}

// UpdateModerationSubmission
// @Summary Update moderation submission
// @Description Replace staged submission data while it is under moderation
// @Tags moderation
// @Accept json
// @Produce json
// @Param submission_id path int true "Submission ID"
// @Param data body presenters.SubmissionUpsertRequest true "Submission payload"
// @Success 200 {object} presenters.SubmissionResponse
// @Failure 400 {object} presenters.ErrorResponse
// @Failure 401 {object} presenters.ErrorResponse
// @Failure 403 {object} presenters.ErrorResponse
// @Failure 404 {object} presenters.ErrorResponse
// @Failure 409 {object} presenters.ErrorResponse
// @Failure 502 {object} presenters.ErrorResponse
// @Router /moderation/submissions/{submission_id} [put]
func UpdateModerationSubmission(ctx *gin.Context, a *app.App) {
	submissionID, err := parsePathInt64(ctx, "submission_id")
	if err != nil {
		ctx.JSON(http.StatusBadRequest, presenters.Error(err))
		return
	}
	var in presenters.SubmissionUpsertRequest
	if err := ctx.ShouldBindJSON(&in); err != nil {
		ctx.JSON(http.StatusBadRequest, presenters.Error(err))
		return
	}
	actor, statusCode, err := resolveSubmissionActor(ctx)
	if err != nil {
		ctx.JSON(statusCode, presenters.Error(err))
		return
	}
	submission, err := a.SubmissionService.UpdateModeration(
		ctx.Request.Context(),
		actor,
		submissionID,
		mapSubmissionInput(&in),
	)
	if err != nil {
		ctx.JSON(mapGRPCToHTTP(err), presenters.Error(err))
		return
	}
	ctx.JSON(http.StatusOK, presenters.SubmissionResponse{Submission: mapSubmission(submission)})
}

// ModerateSubmission
// @Summary Moderate submission
// @Description Approve or reject a submission
// @Tags moderation
// @Accept json
// @Produce json
// @Param submission_id path int true "Submission ID"
// @Param data body presenters.ModerateSubmissionRequest true "Moderation decision"
// @Success 200 {object} presenters.SubmissionResponse
// @Failure 400 {object} presenters.ErrorResponse
// @Failure 401 {object} presenters.ErrorResponse
// @Failure 403 {object} presenters.ErrorResponse
// @Failure 404 {object} presenters.ErrorResponse
// @Failure 409 {object} presenters.ErrorResponse
// @Failure 502 {object} presenters.ErrorResponse
// @Router /moderation/submissions/{submission_id}/moderate [post]
func ModerateSubmission(ctx *gin.Context, a *app.App) {
	submissionID, err := parsePathInt64(ctx, "submission_id")
	if err != nil {
		ctx.JSON(http.StatusBadRequest, presenters.Error(err))
		return
	}
	var in presenters.ModerateSubmissionRequest
	if err := ctx.ShouldBindJSON(&in); err != nil {
		ctx.JSON(http.StatusBadRequest, presenters.Error(err))
		return
	}
	actor, statusCode, err := resolveSubmissionActor(ctx)
	if err != nil {
		ctx.JSON(statusCode, presenters.Error(err))
		return
	}
	submission, err := a.SubmissionService.Moderate(
		ctx.Request.Context(),
		actor,
		submissionID,
		&domain.ModerationDecision{
			Action:  in.Action,
			Comment: in.Comment,
		},
	)
	if err != nil {
		ctx.JSON(mapGRPCToHTTP(err), presenters.Error(err))
		return
	}
	ctx.JSON(http.StatusOK, presenters.SubmissionResponse{Submission: mapSubmission(submission)})
}

func mapSubmissionInput(in *presenters.SubmissionUpsertRequest) *domain.SubmissionUpsertInput {
	if in == nil {
		return &domain.SubmissionUpsertInput{}
	}
	return &domain.SubmissionUpsertInput{
		SourceIdentifier: in.SourceIdentifier,
		Title:            in.Title,
		Abstract:         in.Abstract,
		Year:             in.Year,
		BestOALocation:   in.BestOALocation,
		ReferencedWorks:  append([]string(nil), in.ReferencedWorks...),
		RelatedWorks:     append([]string(nil), in.RelatedWorks...),
	}
}

func resolveSubmissionActor(ctx *gin.Context) (domain.SubmissionActor, int, error) {
	userID, statusCode, err := resolveUserID(ctx, 0)
	if err != nil {
		return domain.SubmissionActor{}, statusCode, err
	}
	return domain.SubmissionActor{
		UserID: userID,
		Roles:  authRoles(ctx),
	}, 0, nil
}
