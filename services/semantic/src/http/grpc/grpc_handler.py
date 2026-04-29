from __future__ import annotations

import math

import grpc

from src.domain.models.search import SearchResult
from src.domain.models.chat import ChatMessage, ChatModel
from src.domain.models.paper import PaperModel
from src.domain.models.submission import SubmissionModel
from src.http.grpc import service_pb2, service_pb2_grpc
from src.http.grpc.auth import (
    ROLE_MODERATOR,
    AuthenticationError,
    AuthorizationError,
    RequestAuthContext,
    extract_auth_context,
)
from src.lib.logger import Logger
from src.services.chat_service import ChatService
from src.services.ingestion.ingestion_service import IngestionService
from src.services.search.search_service import SearchService
from src.services.submission_service import (
    SubmissionNotFoundError,
    SubmissionPermissionError,
    SubmissionService,
    SubmissionStateError,
    SubmissionValidationError,
)
from src.services.user_service import UserService


class SemanticServiceHandlerGrpc(service_pb2_grpc.SemanticServiceServicer):
    def __init__(
        self,
        search_service: SearchService,
        chat_service: ChatService,
        user_service: UserService,
        logger: Logger,
        ingestion_service: IngestionService | None = None,
        submission_service: SubmissionService | None = None,
    ):
        self.logger = logger
        self.search_service = search_service
        self.user_service = user_service
        self.chat_service = chat_service
        self.ingestion_service = ingestion_service
        self.submission_service = submission_service

    def SearchPaper(self, request: service_pb2.SearchRequest, context: grpc.ServicerContext) -> service_pb2.ChatMessage:
        self.logger.info(f"SearchPaper request: {request.Input_data}")
        try:
            if request.Chat_id == 0:
                self.logger.error("SearchPaper failed missing argument chatID")
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details("missing argument chatID")
                return service_pb2.ChatMessage()

            if not self.chat_service.is_chat_owner(request.Chat_id, request.User_id):
                context.set_code(grpc.StatusCode.PERMISSION_DENIED)
                return service_pb2.ChatMessage()

            matching_papers = self.search_service.search_paper(request.Input_data)
            res = self.chat_service.record_chat_message(
                request.Chat_id,
                request.Input_data,
                matching_papers,
            )
            return self._chat_message_to_proto(res)
        except Exception as e:
            self.logger.error("SearchPaper failed", error=str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return service_pb2.ChatMessage()

    def AddPaper(self, request: service_pb2.AddRequest, context: grpc.ServicerContext) -> service_pb2.PaperResponse:
        self.logger.info(f"AddPaper compatibility request: {request.Title}")
        if self.submission_service is None:
            context.set_code(grpc.StatusCode.UNIMPLEMENTED)
            context.set_details("submission service is not configured")
            return service_pb2.PaperResponse()

        try:
            auth = self._require_auth(context)
            submission = self.submission_service.create_or_submit_compat_submission(
                user_id=auth.user_id,
                source_identifier=request.ID or None,
                title=request.Title,
                abstract=request.Abstract,
                year=int(request.Year) if request.Year else None,
                best_oa_location=request.Best_oa_location or None,
                referenced_works=[item.ID for item in request.Referenced_works],
                related_works=[item.ID for item in request.Related_works],
            )
            return service_pb2.PaperResponse(
                ID=request.ID,
                Title=(request.Title or "").strip(),
                Abstract=(request.Abstract or "").strip(),
                Year=request.Year,
                Best_oa_location=request.Best_oa_location,
                State=f"pending:{submission.submission_id}",
                Referenced_works=[item.ID for item in request.Referenced_works],
                Related_works=[item.ID for item in request.Related_works],
            )
        except Exception as exc:
            return self._handle_submission_exception(
                context,
                exc,
                empty_response=service_pb2.PaperResponse(),
                log_message="AddPaper compatibility failed",
            )

    def CreateMySubmission(
        self,
        request: service_pb2.CreateMySubmissionRequest,
        context: grpc.ServicerContext,
    ) -> service_pb2.SubmissionResponse:
        try:
            auth = self._require_auth(context)
            submission = self._require_submission_service().create_my_submission(
                user_id=auth.user_id,
                source_identifier=request.Source_identifier or None,
                title=request.Title,
                abstract=request.Abstract,
                year=int(request.Year) if request.Year else None,
                best_oa_location=request.Best_oa_location or None,
                referenced_works=list(request.Referenced_works),
                related_works=list(request.Related_works),
            )
            return service_pb2.SubmissionResponse(Submission=self._submission_to_proto(submission))
        except Exception as exc:
            return self._handle_submission_exception(
                context,
                exc,
                empty_response=service_pb2.SubmissionResponse(),
                log_message="CreateMySubmission failed",
            )

    def UpdateMySubmission(
        self,
        request: service_pb2.UpdateMySubmissionRequest,
        context: grpc.ServicerContext,
    ) -> service_pb2.SubmissionResponse:
        try:
            auth = self._require_auth(context)
            submission = self._require_submission_service().update_my_submission(
                user_id=auth.user_id,
                submission_id=int(request.Submission_id),
                source_identifier=request.Source_identifier or None,
                title=request.Title,
                abstract=request.Abstract,
                year=int(request.Year) if request.Year else None,
                best_oa_location=request.Best_oa_location or None,
                referenced_works=list(request.Referenced_works),
                related_works=list(request.Related_works),
            )
            return service_pb2.SubmissionResponse(Submission=self._submission_to_proto(submission))
        except Exception as exc:
            return self._handle_submission_exception(
                context,
                exc,
                empty_response=service_pb2.SubmissionResponse(),
                log_message="UpdateMySubmission failed",
            )

    def DeleteMySubmission(
        self,
        request: service_pb2.DeleteMySubmissionRequest,
        context: grpc.ServicerContext,
    ) -> service_pb2.ErrorResponse:
        try:
            auth = self._require_auth(context)
            self._require_submission_service().delete_my_submission(
                user_id=auth.user_id,
                submission_id=int(request.Submission_id),
            )
            return service_pb2.ErrorResponse()
        except Exception as exc:
            return self._handle_submission_exception(
                context,
                exc,
                empty_response=service_pb2.ErrorResponse(),
                log_message="DeleteMySubmission failed",
            )

    def GetMySubmission(
        self,
        request: service_pb2.GetMySubmissionRequest,
        context: grpc.ServicerContext,
    ) -> service_pb2.SubmissionResponse:
        try:
            auth = self._require_auth(context)
            submission = self._require_submission_service().get_my_submission(
                user_id=auth.user_id,
                submission_id=int(request.Submission_id),
            )
            return service_pb2.SubmissionResponse(Submission=self._submission_to_proto(submission))
        except Exception as exc:
            return self._handle_submission_exception(
                context,
                exc,
                empty_response=service_pb2.SubmissionResponse(),
                log_message="GetMySubmission failed",
            )

    def ListMySubmissions(
        self,
        request: service_pb2.ListMySubmissionsRequest,
        context: grpc.ServicerContext,
    ) -> service_pb2.SubmissionListResponse:
        try:
            auth = self._require_auth(context)
            items, total, limit, offset = self._require_submission_service().list_my_submissions(
                user_id=auth.user_id,
                statuses=list(request.Statuses),
                limit=int(request.Limit),
                offset=int(request.Offset),
            )
            return self._submission_list_to_proto(items, total=total, limit=limit, offset=offset)
        except Exception as exc:
            return self._handle_submission_exception(
                context,
                exc,
                empty_response=service_pb2.SubmissionListResponse(),
                log_message="ListMySubmissions failed",
            )

    def SubmitMySubmission(
        self,
        request: service_pb2.SubmitMySubmissionRequest,
        context: grpc.ServicerContext,
    ) -> service_pb2.SubmissionResponse:
        try:
            auth = self._require_auth(context)
            submission = self._require_submission_service().submit_my_submission(
                user_id=auth.user_id,
                submission_id=int(request.Submission_id),
            )
            return service_pb2.SubmissionResponse(Submission=self._submission_to_proto(submission))
        except Exception as exc:
            return self._handle_submission_exception(
                context,
                exc,
                empty_response=service_pb2.SubmissionResponse(),
                log_message="SubmitMySubmission failed",
            )

    def ListModerationQueue(
        self,
        request: service_pb2.ListModerationQueueRequest,
        context: grpc.ServicerContext,
    ) -> service_pb2.SubmissionListResponse:
        try:
            self._require_moderator(context)
            items, total, limit, offset = self._require_submission_service().list_moderation_queue(
                statuses=list(request.Statuses),
                limit=int(request.Limit),
                offset=int(request.Offset),
            )
            return self._submission_list_to_proto(items, total=total, limit=limit, offset=offset)
        except Exception as exc:
            return self._handle_submission_exception(
                context,
                exc,
                empty_response=service_pb2.SubmissionListResponse(),
                log_message="ListModerationQueue failed",
            )

    def GetModerationSubmission(
        self,
        request: service_pb2.GetModerationSubmissionRequest,
        context: grpc.ServicerContext,
    ) -> service_pb2.SubmissionResponse:
        try:
            self._require_moderator(context)
            submission = self._require_submission_service().get_moderation_submission(
                submission_id=int(request.Submission_id),
            )
            return service_pb2.SubmissionResponse(Submission=self._submission_to_proto(submission))
        except Exception as exc:
            return self._handle_submission_exception(
                context,
                exc,
                empty_response=service_pb2.SubmissionResponse(),
                log_message="GetModerationSubmission failed",
            )

    def UpdateModerationSubmission(
        self,
        request: service_pb2.UpdateModerationSubmissionRequest,
        context: grpc.ServicerContext,
    ) -> service_pb2.SubmissionResponse:
        try:
            self._require_moderator(context)
            submission = self._require_submission_service().update_moderation_submission(
                submission_id=int(request.Submission_id),
                source_identifier=request.Source_identifier or None,
                title=request.Title,
                abstract=request.Abstract,
                year=int(request.Year) if request.Year else None,
                best_oa_location=request.Best_oa_location or None,
                referenced_works=list(request.Referenced_works),
                related_works=list(request.Related_works),
            )
            return service_pb2.SubmissionResponse(Submission=self._submission_to_proto(submission))
        except Exception as exc:
            return self._handle_submission_exception(
                context,
                exc,
                empty_response=service_pb2.SubmissionResponse(),
                log_message="UpdateModerationSubmission failed",
            )

    def ModerateSubmission(
        self,
        request: service_pb2.ModerateSubmissionRequest,
        context: grpc.ServicerContext,
    ) -> service_pb2.SubmissionResponse:
        try:
            auth = self._require_moderator(context)
            submission = self._require_submission_service().moderate_submission(
                submission_id=int(request.Submission_id),
                moderator_user_id=auth.user_id,
                action=request.Action,
                comment=request.Comment or None,
            )
            return service_pb2.SubmissionResponse(Submission=self._submission_to_proto(submission))
        except Exception as exc:
            return self._handle_submission_exception(
                context,
                exc,
                empty_response=service_pb2.SubmissionResponse(),
                log_message="ModerateSubmission failed",
            )

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

    def _require_auth(self, context: grpc.ServicerContext) -> RequestAuthContext:
        return extract_auth_context(context, user_service=self.user_service)

    def _require_moderator(self, context: grpc.ServicerContext) -> RequestAuthContext:
        auth = self._require_auth(context)
        auth.require_role(ROLE_MODERATOR)
        return auth

    def _require_submission_service(self) -> SubmissionService:
        if self.submission_service is None:
            raise RuntimeError("submission service is not configured")
        return self.submission_service

    def _handle_submission_exception(self, context: grpc.ServicerContext, exc: Exception, *, empty_response, log_message: str):
        if isinstance(exc, AuthenticationError):
            code = grpc.StatusCode.UNAUTHENTICATED
        elif isinstance(exc, (AuthorizationError, SubmissionPermissionError)):
            code = grpc.StatusCode.PERMISSION_DENIED
        elif isinstance(exc, SubmissionNotFoundError):
            code = grpc.StatusCode.NOT_FOUND
        elif isinstance(exc, SubmissionValidationError):
            code = grpc.StatusCode.INVALID_ARGUMENT
        elif isinstance(exc, SubmissionStateError):
            code = grpc.StatusCode.FAILED_PRECONDITION
        elif isinstance(exc, RuntimeError) and str(exc) == "submission service is not configured":
            code = grpc.StatusCode.UNIMPLEMENTED
        else:
            code = grpc.StatusCode.INTERNAL
        self.logger.error(log_message, error=str(exc))
        context.set_code(code)
        context.set_details(str(exc))
        return empty_response

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
    
    @staticmethod
    def _to_float(value) -> float:
        try:
            if value is None:
                return 0
            if isinstance(value, float):
                return float(value)
            return 0
        except Exception:
            try:
                return float(value)
            except Exception:
                return 0

    @classmethod
    def _paper_identifiers_to_proto(cls, value) -> list[service_pb2.PaperIdentifier]:
        identifiers: list[service_pb2.PaperIdentifier] = []
        for item in value or []:
            if isinstance(item, dict):
                type_value = item.get("type") or item.get("Type")
                identifier_value = item.get("value") or item.get("Value")
            else:
                type_value = getattr(item, "type", None) or getattr(item, "Type", None)
                identifier_value = getattr(item, "value", None) or getattr(item, "Value", None)
            if not type_value and not identifier_value:
                continue
            identifiers.append(
                service_pb2.PaperIdentifier(
                    Type=cls._to_str(type_value),
                    Value=cls._to_str(identifier_value),
                )
            )
        return identifiers

    @classmethod
    def _paper_to_proto(cls, paper: PaperModel) -> service_pb2.PaperResponse:
        return service_pb2.PaperResponse(
            ID=cls._to_str(paper.ID),
            Title=cls._to_str(paper.Title),
            Abstract=cls._to_str(paper.Abstract),
            Year=cls._to_int(paper.Year),
            Best_oa_location=cls._to_str(paper.Best_oa_location),
            Referenced_works=[cls._to_str(item) for item in getattr(paper, "Referenced_works", [])],
            Related_works=[cls._to_str(item) for item in getattr(paper, "Related_works", [])],
            Cited_by_count=cls._to_int(getattr(paper, "Cited_by_count", 0)),
            Authors=[cls._to_str(item) for item in getattr(paper, "Authors", [])],
            Institutions=[cls._to_str(item) for item in getattr(paper, "Institutions", [])],
            Identifiers=cls._paper_identifiers_to_proto(getattr(paper, "Identifiers", [])),
        )
    
    @classmethod
    def _search_res_to_proto(cls, paper: SearchResult) -> service_pb2.ChatPaperResponse:
        return service_pb2.ChatPaperResponse(
            ID=cls._to_str(paper.paper.ID),
            Title=cls._to_str(paper.paper.Title),
            Abstract=cls._to_str(paper.paper.Abstract),
            Year=cls._to_int(paper.paper.Year),
            Best_oa_location=cls._to_str(paper.paper.Best_oa_location),
            Referenced_works=[cls._to_str(item) for item in getattr(paper.paper, "Referenced_works", [])],
            Related_works=[cls._to_str(item) for item in getattr(paper.paper, "Related_works", [])],
            Cited_by_count=cls._to_int(getattr(paper.paper, "Cited_by_count", 0)),
            Authors=[cls._to_str(item) for item in getattr(paper.paper, "Authors", [])],
            Institutions=[cls._to_str(item) for item in getattr(paper.paper, "Institutions", [])],
            Identifiers=cls._paper_identifiers_to_proto(getattr(paper.paper, "Identifiers", [])),
            Score=cls._to_float(paper.score)
        )

    @classmethod
    def _submission_to_proto(cls, submission: SubmissionModel) -> service_pb2.SubmissionRecord:
        return service_pb2.SubmissionRecord(
            Submission_id=cls._to_int(submission.submission_id),
            Created_by_user_id=cls._to_int(submission.created_by_user_id),
            Source_identifier=cls._to_str(submission.source_identifier),
            Title=cls._to_str(submission.title),
            Abstract=cls._to_str(submission.abstract),
            Year=cls._to_int(submission.year),
            Best_oa_location=cls._to_str(submission.best_oa_location),
            Referenced_works=list(submission.referenced_works),
            Related_works=list(submission.related_works),
            Status=cls._to_str(submission.status),
            Moderated_by_user_id=cls._to_int(submission.moderated_by_user_id),
            Moderation_comment=cls._to_str(submission.moderation_comment),
            Approved_paper_id=cls._to_int(submission.approved_paper_id),
            Created_at=cls._to_str(submission.created_at),
            Updated_at=cls._to_str(submission.updated_at),
            Submitted_at=cls._to_str(submission.submitted_at),
            Moderated_at=cls._to_str(submission.moderated_at),
        )

    @classmethod
    def _submission_list_to_proto(
        cls,
        submissions: list[SubmissionModel],
        *,
        total: int,
        limit: int,
        offset: int,
    ) -> service_pb2.SubmissionListResponse:
        response = service_pb2.SubmissionListResponse(
            Total=cls._to_int(total),
            Limit=cls._to_int(limit),
            Offset=cls._to_int(offset),
        )
        for submission in submissions:
            response.Items.append(cls._submission_to_proto(submission))
        return response

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
        chat_papers = service_pb2.ChatPapersResponse()
        for result in message.search_res:
            chat_papers.Papers.append(cls._search_res_to_proto(result))
        created_at = ""
        if getattr(message, "created_at", None) is not None:
            created_at = cls._to_str(message.created_at)
        return service_pb2.ChatMessage(
            Search_query=cls._to_str(message.search_query),
            Created_at=created_at,
            papers=chat_papers,
        )
