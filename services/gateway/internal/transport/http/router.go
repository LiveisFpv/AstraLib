package http

import (
	"VKR_gateway_service/internal/app"
	"VKR_gateway_service/internal/transport/http/handlers"

	"github.com/gin-gonic/gin"
)

func ChatRouter(r *gin.RouterGroup, a *app.App) {
	r.POST("", func(ctx *gin.Context) { handlers.CreateChat(ctx, a) })
	r.GET("", func(ctx *gin.Context) { handlers.GetUserChats(ctx, a) })
	r.GET("/:chat_id/history", func(ctx *gin.Context) { handlers.GetChatHistory(ctx, a) })
	r.POST("/:chat_id/history", func(ctx *gin.Context) { handlers.CreateChatHistory(ctx, a) })
	r.PUT("/:chat_id", func(ctx *gin.Context) { handlers.UpdateChat(ctx, a) })
	r.DELETE("/:chat_id", func(ctx *gin.Context) { handlers.DeleteChat(ctx, a) })
}

func SubmissionsRouter(r *gin.RouterGroup, a *app.App) {
	r.POST("", func(ctx *gin.Context) { handlers.CreateSubmission(ctx, a) })
	r.GET("", func(ctx *gin.Context) { handlers.ListMySubmissions(ctx, a) })
	r.GET("/:submission_id", func(ctx *gin.Context) { handlers.GetMySubmission(ctx, a) })
	r.PUT("/:submission_id", func(ctx *gin.Context) { handlers.UpdateMySubmission(ctx, a) })
	r.DELETE("/:submission_id", func(ctx *gin.Context) { handlers.DeleteMySubmission(ctx, a) })
	r.POST("/:submission_id/submit", func(ctx *gin.Context) { handlers.SubmitMySubmission(ctx, a) })
}

func ModerationRouter(r *gin.RouterGroup, a *app.App) {
	r.GET("", func(ctx *gin.Context) { handlers.ListModerationSubmissions(ctx, a) })
	r.GET("/:submission_id", func(ctx *gin.Context) { handlers.GetModerationSubmission(ctx, a) })
	r.PUT("/:submission_id", func(ctx *gin.Context) { handlers.UpdateModerationSubmission(ctx, a) })
	r.POST("/:submission_id/moderate", func(ctx *gin.Context) { handlers.ModerateSubmission(ctx, a) })
}

func SSORouter(r *gin.RouterGroup, a *app.App) {

}
