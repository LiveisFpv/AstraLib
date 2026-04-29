from typing import List, Optional

from src.domain.models.paper import PaperModel
from src.domain.models.search import SearchResult


class ChatModel:
    def __init__(self,id,user_id,updated_at,title):
        self.id=id
        self.user_id=user_id
        self.updated_at=updated_at
        self.title=title
class ChatMessage:
    def __init__(self,search_query,created_at,search_res:List[SearchResult]):
        self.search_query=search_query
        self.created_at=created_at
        self.search_res=search_res