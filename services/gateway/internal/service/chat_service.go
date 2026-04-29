package service

import (
	pb "VKR_gateway_service/gen/go"
	"VKR_gateway_service/internal/domain"
	"VKR_gateway_service/internal/transport/rpc"
	"context"
	"errors"
	"fmt"

	"github.com/sirupsen/logrus"
)

var (
	ErrCreateChatRPC      = errors.New("RPC error create chat, bad status code")
	ErrGetUserChatsRPC    = errors.New("RPC error get user's chats, bad status code")
	ErrGetChatMessagesRPC = errors.New("RPC error get chat's messages, bad status code")
	ErrSearchPaperRPC     = errors.New("RPC error failed to search papers, bad status code")
	ErrUpdateChatRPC      = errors.New("RPC error failed to update paper, bad status code")
	ErrDeleteChatRPC      = errors.New("RPC error failed to delete chat, bad status code")
)

type ChatService interface {
	CreateChat(ctx context.Context, user_id int, title string) (*domain.Chat, error)
	UpdateChat(ctx context.Context, chat *domain.Chat) (*domain.Chat, error)
	DeleteChat(ctx context.Context, chat_id, user_id int) error
	GetUserChats(ctx context.Context, user_id int) ([]*domain.Chat, error)
	GetChatHistory(ctx context.Context, chat_id, user_id int) ([]*domain.ChatHistoryMessage, error)
	Search(ctx context.Context, input string, chat_id, user_id int) (*domain.ChatHistoryMessage, error)
}

type chatService struct {
	SemanticClient rpc.SemanticClient
	logger         *logrus.Logger
}

func NewChatService(SemanticClient rpc.SemanticClient, logger *logrus.Logger) ChatService {
	return &chatService{
		SemanticClient: SemanticClient,
		logger:         logger,
	}
}

func (c *chatService) CreateChat(ctx context.Context, user_id int, title string) (*domain.Chat, error) {
	req := &pb.Chat{
		UserId: int64(user_id),
		Title:  title,
	}
	resp, err := c.SemanticClient.CreateNewChat(ctx, req)
	if err != nil {
		c.logger.WithError(err).WithField("user_id", user_id).Error("AI CreateNewChat RPC failed")
		return nil, err
	}

	chat := resp.GetChat()
	return mapChat(chat), nil
}

func (c *chatService) DeleteChat(ctx context.Context, chat_id int, user_id int) error {
	req := &pb.DeleteChatReq{ChatId: int64(chat_id), UserId: int64(user_id)}
	resp, err := c.SemanticClient.DeleteChat(ctx, req)
	if err != nil {
		c.logger.WithError(err).WithFields(map[string]interface{}{
			"chat_id": chat_id,
			"user_id": user_id,
		}).Error("AI Update chat RPC failed")
		return err
	}

	if resp.Error != "" {
		return fmt.Errorf(resp.Error)
	}

	return nil
}

func (c *chatService) GetChatHistory(ctx context.Context, chat_id int, user_id int) ([]*domain.ChatHistoryMessage, error) {
	req := &pb.HistoryReq{ChatId: int64(chat_id), UserId: int64(user_id)}
	resp, err := c.SemanticClient.GetChatHistory(ctx, req)
	if err != nil {
		c.logger.WithError(err).WithField("chat_id", chat_id).Error("AI GetChatHistory RPC failed")
		return nil, err
	}

	messages := make([]*domain.ChatHistoryMessage, 0, len(resp.GetChatMessages()))
	for _, message := range resp.GetChatMessages() {
		messages = append(messages, &domain.ChatHistoryMessage{
			SearchQuery: message.SearchQuery,
			CreatedAt:   message.CreatedAt,
			Papers:      mapChatPapers(message.GetPapers().GetPapers()),
		})
	}
	return messages, nil
}

func (c *chatService) GetUserChats(ctx context.Context, user_id int) ([]*domain.Chat, error) {
	req := &pb.UserChatsReq{UserId: int64(user_id)}
	resp, err := c.SemanticClient.GetUserChats(ctx, req)
	if err != nil {
		c.logger.WithError(err).WithField("user_id", user_id).Error("AI GetUserChats RPC failed")
		return nil, err
	}

	chats := resp.GetChats()

	chats_dom := make([]*domain.Chat, 0, len(chats))

	for _, chat := range chats {
		chats_dom = append(chats_dom, mapChat(chat))
	}
	return chats_dom, nil
}

func (c *chatService) Search(ctx context.Context, input string, chat_id int, user_id int) (*domain.ChatHistoryMessage, error) {
	req := &pb.SearchRequest{
		InputData: input,
		ChatId:    int64(chat_id),
		UserId:    int64(user_id),
	}
	resp, err := c.SemanticClient.SearchPaper(ctx, req)
	if err != nil {
		c.logger.WithError(err).WithFields(map[string]interface{}{
			"chat_id": chat_id,
			"user_id": user_id,
		}).Error("AI Update chat RPC failed")
		return nil, err
	}

	return &domain.ChatHistoryMessage{
		SearchQuery: resp.GetSearchQuery(),
		CreatedAt:   resp.GetCreatedAt(),
		Papers:      mapChatPapers(resp.GetPapers().GetPapers()),
	}, nil
}

func (c *chatService) UpdateChat(ctx context.Context, chat *domain.Chat) (*domain.Chat, error) {
	req := &pb.UpdateChatReq{
		ChatId: chat.ChatId,
		UserId: chat.UserId,
		Title:  chat.Title,
	}
	resp, err := c.SemanticClient.UpdateChat(ctx, req)
	if err != nil {
		c.logger.WithError(err).WithFields(map[string]interface{}{
			"chat_id": chat.ChatId,
			"user_id": chat.UserId,
		}).Error("Update Chat RPC failed")
		return nil, err
	}
	return mapChat(resp.GetChat()), nil
}
