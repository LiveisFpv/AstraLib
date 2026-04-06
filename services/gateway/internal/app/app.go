package app

import (
	pb "VKR_gateway_service/gen/go"
	"VKR_gateway_service/internal/config"
	"VKR_gateway_service/internal/service"

	"github.com/sirupsen/logrus"
)

type App struct {
	Config            *config.Config
	ChatService       service.ChatService
	PaperService      service.PaperService
	SubmissionService service.SubmissionService
	Logger            *logrus.Logger
	// gRPC client for external AI service
	AI pb.SemanticServiceClient
}

func NewApp(
	cfg *config.Config,
	Logger *logrus.Logger,
	AI pb.SemanticServiceClient,
) *App {
	ChatService := service.NewChatService(AI, Logger)
	PaperService := service.NewPaperService(AI, Logger)
	SubmissionService := service.NewSubmissionService(AI, Logger)
	return &App{
		Config:            cfg,
		ChatService:       ChatService,
		PaperService:      PaperService,
		SubmissionService: SubmissionService,
		Logger:            Logger,
		AI:                AI,
	}
}
