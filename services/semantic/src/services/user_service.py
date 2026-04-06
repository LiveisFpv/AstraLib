from __future__ import annotations

from typing import Optional
from src.domain.models.user import UserModel
from src.storage.user_repository import UserRepository

class UserService:
    def __init__(self, repository:UserRepository):
        self.repository=repository
    
    def create_user(self, user:UserModel)->str:
        return self.repository.create_user(user)

    def get_user(self, user_id:int)->Optional[UserModel]:
        return self.repository.get_user(user_id)

    def ensure_user(self, user_id: int) -> UserModel:
        existing = self.repository.get_user(user_id)
        if existing is not None:
            return existing
        user = UserModel(user_id)
        self.repository.create_user(user)
        return user
