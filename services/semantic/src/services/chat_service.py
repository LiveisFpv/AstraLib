from __future__ import annotations

from typing import List, Optional
from src.domain.models.chat import ChatMessage, ChatModel
from src.domain.models.paper import PaperModel
from src.storage.chat_repository import ChatRepository
from src.services.user_service import UserService

class ChatService:
    def __init__(self,repository:ChatRepository,user_service: UserService):
        self.repository=repository
        self.user_service=user_service

    def create_chat(self, user_id: int, title: Optional[str] = None) -> ChatModel:
        self.user_service.ensure_user(user_id)
        return self.repository.create_chat(user_id, title=title)

    def update_chat(self, chat:ChatModel)->ChatModel:
        self.user_service.ensure_user(chat.user_id)
        return self.repository.update_chat(chat)
    
    def delete_chat(self, chat_id:int,user_id:int)->str|None:
        self.user_service.ensure_user(user_id)
        return self.repository.delete_chat(chat_id,user_id)

    def get_chat_history(self, chat_id:int)->List[ChatMessage]:
        return self.repository.get_chat_history(chat_id)
    
    def get_user_chats(self,user_id:int)->List[ChatModel]:
        self.user_service.ensure_user(user_id)
        return self.repository.get_user_chats(user_id)

    def record_chat_message(self, chat_id: int, search_query: str, papers: List[PaperModel]) -> ChatMessage:
        return self.repository.create_chat_message(chat_id, search_query, papers)

    def is_chat_owner(self, chat_id:int,user_id:int)->bool:
        self.user_service.ensure_user(user_id)
        return self.repository.is_chat_owner(chat_id,user_id)
