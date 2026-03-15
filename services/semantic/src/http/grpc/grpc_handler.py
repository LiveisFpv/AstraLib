from src.lib.logger import Logger
from src.http.grpc import service_pb2, service_pb2_grpc
from src.services.search.search_service import SearchService
from src.services.chat_service import ChatService
from src.services.ingestion.ingestion_service import IngestionService
from src.services.ingestion.models import AuthorSubmission
from src.services.user_service import UserService
from src.domain.models.chat import ChatModel, ChatMessage
from src.domain.models.paper import PaperModel
import grpc
import math


class SemanticServiceHandlerGrpc(service_pb2_grpc.SemanticServiceServicer):
    def __init__(
        self,
        search_service: SearchService,
        chat_service: ChatService,
        user_service: UserService,
        logger: Logger,
        ingestion_service: IngestionService | None = None,
    ):
        self.logger = logger
        self.search_service = search_service
        self.user_service = user_service
        self.chat_service = chat_service
        self.ingestion_service = ingestion_service

    # ! TODO add handlers for chat and user services
    def SearchPaper(self, request: service_pb2.SearchRequest, context: grpc.ServicerContext) -> service_pb2.ChatMessage:
        self.logger.info(f"SearchPaper request: {request.Input_data}")
        try:
            if request.Chat_id == 0:
                self.logger.error("SearchPaper failed missing argument chatID")
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details("missing argument chatID")
                return service_pb2.ChatMessage()

            # ! Check user id for chat id
            if not self.chat_service.is_chat_owner(request.Chat_id, request.User_id):
                context.set_code(grpc.StatusCode.PERMISSION_DENIED)
                return service_pb2.ChatMessage()

            matching_papers = self.search_service.search_paper(request.Input_data)

            res = self.chat_service.record_chat_message(
                request.Chat_id,
                request.Input_data,
                matching_papers,
            )
            message = self._chat_message_to_proto(res)
            return message

        except Exception as e:
            self.logger.error("SearchPaper failed", error=str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return service_pb2.ChatMessage()

    def AddPaper(self, request: service_pb2.AddRequest, context: grpc.ServicerContext) -> service_pb2.PaperResponse:
        self.logger.info(f"AddPaper request: {request.Title}")

        if self.ingestion_service is None:
            context.set_code(grpc.StatusCode.UNIMPLEMENTED)
            context.set_details("ingestion service is not configured")
            return service_pb2.PaperResponse()

        title = request.Title.strip()
        abstract = request.Abstract.strip()
        if not title and not abstract:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("paper must contain title or abstract")
            return service_pb2.PaperResponse()

        try:
            submission = AuthorSubmission(
                identifier=request.ID or None,
                title=title,
                abstract=abstract,
                year=int(request.Year) if request.Year else None,
                best_oa_location=request.Best_oa_location or None,
                referenced_works=[item.ID for item in request.Referenced_works],
                related_works=[item.ID for item in request.Related_works],
                state=request.State or "approved",
            )
            task_id = self.ingestion_service.enqueue_author_submission(submission)
            return service_pb2.PaperResponse(
                ID=request.ID,
                Title=title,
                Abstract=abstract,
                Year=request.Year,
                Best_oa_location=request.Best_oa_location,
                State=f"queued:{task_id}",
            )
        except Exception as e:
            self.logger.error("AddPaper failed", error=str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return service_pb2.PaperResponse()

    def CreateNewChat(self, request: service_pb2.Chat, context: grpc.ServicerContext) -> service_pb2.ChatResp:
        self.logger.info(f"CreateNewChat request: user_id={request.User_id}")
        try:
            chat = self.chat_service.create_chat(request.User_id, title=request.Title)
            return service_pb2.ChatResp(Chat=self._chat_to_proto(chat))
        except Exception as e:
            self.logger.error("CreateNewChat failed", error=str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return service_pb2.ChatResp()

    def GetChatHistory(self, request: service_pb2.HistoryReq, context: grpc.ServicerContext) -> service_pb2.HistoryResp:
        self.logger.info(f"GetChatHistory request: chat_id={request.Chat_id}")
        try:
            # ! Check user id for chat id
            if not self.chat_service.is_chat_owner(request.Chat_id, request.User_id):
                context.set_code(grpc.StatusCode.PERMISSION_DENIED)
                return service_pb2.HistoryResp()
            history = self.chat_service.get_chat_history(request.Chat_id)
            resp = service_pb2.HistoryResp()
            for message in history:
                resp.ChatMessages.append(self._chat_message_to_proto(message))
            return resp
        except Exception as e:
            self.logger.error("GetChatHistory failed", error=str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return service_pb2.HistoryResp()

    def DeleteChat(self, request: service_pb2.DeleteChatReq, context: grpc.ServicerContext) -> service_pb2.ErrorResponse:
        self.logger.info(f"DeleteChat request: chat_id={request.Chat_id} by user_id={request.User_id}")
        try:
            _ = self.chat_service.delete_chat(request.Chat_id, request.User_id)
            return service_pb2.ErrorResponse()
        except RuntimeError as e:
            self.logger.error("Delete Chat failed", error=str(e))
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(str(e))
            return service_pb2.ErrorResponse(Error=str(e))
        except Exception as e:
            self.logger.error("Delete Chat failed", error=str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return service_pb2.ErrorResponse(Error=str(e))

    def GetAuthorPapers(self, request: service_pb2.AuthorPaperReq, context: grpc.ServicerContext) -> service_pb2.PapersResponse:
        return super().GetAuthorPapers(request, context)

    def GetAuthors(self, request: service_pb2.AuthorReq, context: grpc.ServicerContext) -> service_pb2.AuthorsResp:
        return super().GetAuthors(request, context)

    def GetInstitutions(self, request: service_pb2.InstitutionReq, context: grpc.ServicerContext) -> service_pb2.InstitutionsResp:
        return super().GetInstitutions(request, context)

    def GetUserChats(self, request: service_pb2.UserChatsReq, context: grpc.ServicerContext) -> service_pb2.ChatsResp:
        self.logger.info(f"GetUserChats request: user_id={request.User_id}")
        try:
            chats = self.chat_service.get_user_chats(request.User_id)
            resp = service_pb2.ChatsResp()
            for chat in chats:
                resp.Chats.append(self._chat_to_proto(chat))
            return resp
        except Exception as e:
            self.logger.error("GetUserChats failed", error=str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return service_pb2.ChatsResp()

    def UpdateChat(self, request: service_pb2.UpdateChatReq, context: grpc.ServicerContext) -> service_pb2.ChatResp:
        self.logger.info(f"UpdateChat request: chat_id={request.Chat_id}")
        try:
            chat = self.chat_service.update_chat(
                ChatModel(request.Chat_id, request.User_id, None, request.Title)
            )
            return service_pb2.ChatResp(Chat=self._chat_to_proto(chat))
        except RuntimeError as e:
            self.logger.error("UpdateChat failed", error=str(e))
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(str(e))
            return service_pb2.ChatResp()
        except Exception as e:
            self.logger.error("UpdateChat failed", error=str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return service_pb2.ChatResp()

    def AddAuthor(self, request: service_pb2.Author, context: grpc.ServicerContext) -> service_pb2.ErrorResponse:
        return super().AddAuthor(request, context)

    def AddInstitution(self, request: service_pb2.Institution, context: grpc.ServicerContext) -> service_pb2.ErrorResponse:
        return super().AddInstitution(request, context)

    @staticmethod
    def _to_str(value) -> str:
        try:
            return "" if value is None else str(value)
        except Exception:
            return ""

    @staticmethod
    def _to_int(value) -> int:
        try:
            if value is None:
                return 0
            if isinstance(value, float) and math.isnan(value):
                return 0
            return int(value)
        except Exception:
            try:
                return int(float(value))
            except Exception:
                return 0

    @classmethod
    def _paper_to_proto(cls, paper: PaperModel) -> service_pb2.PaperResponse:
        return service_pb2.PaperResponse(
            ID=cls._to_str(paper.ID),
            Title=cls._to_str(paper.Title),
            Abstract=cls._to_str(paper.Abstract),
            Year=cls._to_int(paper.Year),
            Best_oa_location=cls._to_str(paper.Best_oa_location),
        )

    @classmethod
    def _chat_to_proto(cls, chat: ChatModel) -> service_pb2.Chat:
        updated_at = ""
        if getattr(chat, "updated_at", None) is not None:
            updated_at = cls._to_str(chat.updated_at)
        return service_pb2.Chat(
            Chat_id=cls._to_int(chat.id),
            User_id=cls._to_int(chat.user_id),
            Updated_at=updated_at,
            Title=cls._to_str(chat.title),
        )

    @classmethod
    def _chat_message_to_proto(cls, message: ChatMessage) -> service_pb2.ChatMessage:
        papers = service_pb2.PapersResponse()
        for paper in message.papers:
            papers.Papers.append(cls._paper_to_proto(paper))
        created_at = ""
        if getattr(message, "created_at", None) is not None:
            created_at = cls._to_str(message.created_at)
        return service_pb2.ChatMessage(
            Search_query=cls._to_str(message.search_query),
            Created_at=created_at,
            papers=papers,
        )
