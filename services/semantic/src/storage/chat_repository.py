from __future__ import annotations

from typing import List, Optional
from src.domain.models.search import SearchResult
from src.domain.models.chat import ChatMessage, ChatModel
from src.domain.models.paper import PaperModel

import psycopg
from psycopg.rows import dict_row

from src.config.config import DATABASE_SETTINGS

class ChatRepository:
    def __init__(self, *, dsn: str | None = None) -> None:
        self.dsn = dsn or DATABASE_SETTINGS.psycopg_dsn()

    def is_chat_owner(self, chat_id:int,user_id:int)->bool:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            query = """
                SELECT FROM chat
                WHERE chat_id = %s AND user_id = %s
            """
            with conn.cursor() as cur:
                cur.execute(query, (chat_id, user_id))
                if cur.rowcount == 0:
                    return False
            conn.commit()
        return True

    def create_chat(self, user_id: int, title: Optional[str] = None) -> ChatModel:
        title_value = title.strip() if isinstance(title, str) and title.strip() else "New chat"
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            query = """
                INSERT INTO chat (user_id, title)
                VALUES (%s, %s)
                RETURNING chat_id, user_id, updated_at, title
            """
            with conn.cursor() as cur:
                cur.execute(query, (user_id, title_value))
                row = cur.fetchone()
        if not row:
            raise RuntimeError("Failed to create chat")
        return ChatModel(row["chat_id"], row["user_id"], row["updated_at"], row["title"])

    def update_chat(self, chat: ChatModel) -> ChatModel:
        title_value = chat.title.strip() if isinstance(chat.title, str) and chat.title.strip() else None
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            query = """
                UPDATE chat
                SET title = COALESCE(%s, title),
                    updated_at = NOW()
                WHERE chat_id = %s and user_id = %s
                RETURNING chat_id, user_id, updated_at, title
            """
            with conn.cursor() as cur:
                cur.execute(query, (title_value, chat.id, chat.user_id))
                row = cur.fetchone()
        if not row:
            raise RuntimeError("Chat not found")
        return ChatModel(row["chat_id"], row["user_id"], row["updated_at"], row["title"])

    def delete_chat(self, chat_id: int, user_id: int) -> str | None:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            query = """
                DELETE FROM chat 
                WHERE chat_id = %s AND user_id = %s
            """
            with conn.cursor() as cur:
                cur.execute(query, (chat_id, user_id))
                if cur.rowcount == 0:
                    raise RuntimeError("Chat doesn't exist or user doesn't have permission")
            conn.commit()
        return None

    def create_chat_message(self, chat_id: int, search_query: str, search_res: List[SearchResult]) -> ChatMessage:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chat_message (chat_id, search_query)
                    VALUES (%s, %s)
                    RETURNING chat_history_id, created_at
                    """,
                    (chat_id, search_query),
                )
                row = cur.fetchone()
                if not row:
                    raise RuntimeError("Failed to create chat history entry")
                chat_history_id = row["chat_history_id"]
                created_at = row["created_at"]

                if search_res:
                    insert_query = """
                        INSERT INTO search_results (chat_history_id, paper_id, score, rank)
                        VALUES (%s, %s, %s, %s)
                    """
                    values = []
                    search_res.sort(reverse=True,key=lambda x:x.score)
                    for idx, search in enumerate(search_res):
                        paper_id = self._normalize_paper_id(search.paper)
                        if paper_id is None:
                            continue
                        values.append((chat_history_id, paper_id, search.score, idx + 1))
                    if values:
                        cur.executemany(insert_query, values)

                cur.execute(
                    "UPDATE chat SET updated_at = NOW() WHERE chat_id = %s",
                    (chat_id,),
                )
        return ChatMessage(search_query, created_at, search_res)

    def get_chat_history(self, chat_id: int) -> List[ChatMessage]:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            query = """
                WITH message_papers AS (
                    SELECT DISTINCT sr.paper_id
                    FROM chat_message cm
                    JOIN search_results sr ON sr.chat_history_id = cm.chat_history_id
                    WHERE cm.chat_id = %s
                ),
                best_location AS (
                    SELECT
                        paper_id,
                        MAX(CASE WHEN link_type = 'best_oa_landing' THEN url END) AS best_oa_landing,
                        MAX(CASE WHEN link_type = 'best_oa_pdf' THEN url END) AS best_oa_pdf,
                        MAX(CASE WHEN link_type = 'primary_landing' THEN url END) AS primary_landing,
                        MAX(CASE WHEN link_type = 'primary_pdf' THEN url END) AS primary_pdf
                    FROM locations
                    WHERE paper_id IN (SELECT paper_id FROM message_papers)
                    GROUP BY paper_id
                ),
                referenced AS (
                    SELECT
                        ce.src_paper_id AS paper_id,
                        array_agg(
                            DISTINCT CASE
                                WHEN pi.identifier ~ '(^|/)W[0-9]+$'
                                    THEN 'https://openalex.org/' || substring(pi.identifier FROM 'W[0-9]+$')
                                ELSE pi.identifier
                            END
                            ORDER BY CASE
                                WHEN pi.identifier ~ '(^|/)W[0-9]+$'
                                    THEN 'https://openalex.org/' || substring(pi.identifier FROM 'W[0-9]+$')
                                ELSE pi.identifier
                            END
                        ) AS refs
                    FROM citation_edges ce
                    JOIN paper_identifiers pi ON pi.paper_id = ce.dst_paper_id
                    JOIN identifier_types it ON it.identifier_type_id = pi.identifier_type_id
                    WHERE it.name = 'openalex'
                      AND ce.src_paper_id IN (SELECT paper_id FROM message_papers)
                    GROUP BY ce.src_paper_id
                ),
                related AS (
                    SELECT
                        pr.src_paper_id AS paper_id,
                        array_agg(
                            DISTINCT CASE
                                WHEN pi.identifier ~ '(^|/)W[0-9]+$'
                                    THEN 'https://openalex.org/' || substring(pi.identifier FROM 'W[0-9]+$')
                                ELSE pi.identifier
                            END
                            ORDER BY CASE
                                WHEN pi.identifier ~ '(^|/)W[0-9]+$'
                                    THEN 'https://openalex.org/' || substring(pi.identifier FROM 'W[0-9]+$')
                                ELSE pi.identifier
                            END
                        ) AS rels
                    FROM paper_relations pr
                    JOIN paper_relations rev
                        ON rev.src_paper_id = pr.dst_paper_id
                       AND rev.dst_paper_id = pr.src_paper_id
                    JOIN paper_identifiers pi ON pi.paper_id = pr.dst_paper_id
                    JOIN identifier_types it ON it.identifier_type_id = pi.identifier_type_id
                    WHERE it.name = 'openalex'
                      AND pr.src_paper_id IN (SELECT paper_id FROM message_papers)
                    GROUP BY pr.src_paper_id
                ),
                cited AS (
                    SELECT
                        ce.dst_paper_id AS paper_id,
                        COUNT(*) AS cited_by
                    FROM citation_edges ce
                    WHERE ce.dst_paper_id IN (SELECT paper_id FROM message_papers)
                    GROUP BY ce.dst_paper_id
                ),
                authors_cte AS (
                    SELECT
                        pa.paper_id,
                        array_agg(
                            CONCAT_WS(
                                ' ',
                                NULLIF(a.first_name, ''),
                                NULLIF(a.middle_name, ''),
                                NULLIF(a.last_name, '')
                            )
                            ORDER BY pa.author_order NULLS LAST, a.author_id
                        ) AS names
                    FROM paper_authors pa
                    JOIN authors a ON a.author_id = pa.author_id
                    WHERE pa.paper_id IN (SELECT paper_id FROM message_papers)
                    GROUP BY pa.paper_id
                ),
                institutions_cte AS (
                    SELECT
                        pi.paper_id,
                        array_agg(DISTINCT inst.name ORDER BY inst.name) AS names
                    FROM paper_institutions pi
                    JOIN institutions inst ON inst.institution_id = pi.institution_id
                    WHERE pi.paper_id IN (SELECT paper_id FROM message_papers)
                    GROUP BY pi.paper_id
                ),
                identifiers_cte AS (
                    SELECT
                        normalized.paper_id,
                        jsonb_agg(
                            jsonb_build_object('type', normalized.type, 'value', normalized.value)
                            ORDER BY normalized.type, normalized.value
                        ) AS items
                    FROM (
                        SELECT DISTINCT
                            pi.paper_id,
                            it.name AS type,
                            CASE
                                WHEN it.name = 'openalex' AND pi.identifier ~ '(^|/)W[0-9]+$'
                                    THEN 'https://openalex.org/' || substring(pi.identifier FROM 'W[0-9]+$')
                                ELSE pi.identifier
                            END AS value
                        FROM paper_identifiers pi
                        JOIN identifier_types it ON it.identifier_type_id = pi.identifier_type_id
                        WHERE pi.paper_id IN (SELECT paper_id FROM message_papers)
                    ) normalized
                    GROUP BY normalized.paper_id
                )
                SELECT
                    cm.chat_history_id,
                    cm.search_query,
                    cm.created_at,
                    sr.rank,
                    sr.score,
                    p.paper_id,
                    p.title,
                    p.abstract,
                    p.year,
                    COALESCE(best.best_oa_landing, best.best_oa_pdf, best.primary_landing, best.primary_pdf) AS best_oa_location,
                    COALESCE(referenced.refs, ARRAY[]::text[]) AS referenced_works,
                    COALESCE(related.rels, ARRAY[]::text[]) AS related_works,
                    COALESCE(cited.cited_by, 0) AS cited_by_count,
                    COALESCE(sr.rank, 0) AS rank,
                    COALESCE(authors_cte.names, ARRAY[]::text[]) AS authors,
                    COALESCE(institutions_cte.names, ARRAY[]::text[]) AS institutions,
                    COALESCE(identifiers_cte.items, '[]'::jsonb) AS identifiers
                FROM chat_message cm
                LEFT JOIN search_results sr ON sr.chat_history_id = cm.chat_history_id
                LEFT JOIN papers p ON p.paper_id = sr.paper_id
                LEFT JOIN best_location best ON best.paper_id = p.paper_id
                LEFT JOIN referenced ON referenced.paper_id = p.paper_id
                LEFT JOIN related ON related.paper_id = p.paper_id
                LEFT JOIN cited ON cited.paper_id = p.paper_id
                LEFT JOIN authors_cte ON authors_cte.paper_id = p.paper_id
                LEFT JOIN institutions_cte ON institutions_cte.paper_id = p.paper_id
                LEFT JOIN identifiers_cte ON identifiers_cte.paper_id = p.paper_id
                WHERE cm.chat_id = %s
                ORDER BY cm.created_at ASC, sr.rank ASC NULLS LAST, p.paper_id ASC
            """
            with conn.cursor() as cur:
                cur.execute(query, (chat_id, chat_id))
                rows = cur.fetchall()

        messages: dict[int, ChatMessage] = {}
        order: List[int] = []
        for row in rows:
            history_id = row["chat_history_id"]
            if history_id not in messages:
                messages[history_id] = ChatMessage(
                    row["search_query"],
                    row["created_at"],
                    [],
                )
                order.append(history_id)
            paper_id = row["paper_id"]
            if paper_id is None:
                continue
            paper = PaperModel(
                paper_id,
                Title=row.get("title") or "",
                Abstract=row.get("abstract") or "",
                Year=row.get("year") or 0,
                Best_oa_location=row.get("best_oa_location") or "",
                Referenced_works=list(row.get("referenced_works") or []),
                Related_works=list(row.get("related_works") or []),
                Cited_by_count=int(row.get("cited_by_count") or 0),
                Authors=list(row.get("authors") or []),
                Institutions=list(row.get("institutions") or []),
                Identifiers=list(row.get("identifiers") or []),
            )
            score = row.get("score")
            search = SearchResult(paper,score)
            messages[history_id].search_res.append(search)
        return [messages[history_id] for history_id in order]

    def get_user_chats(self, user_id: int) -> List[ChatModel]:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            query = """
                SELECT chat_id, user_id, updated_at, title
                FROM chat
                WHERE user_id = %s
                ORDER BY updated_at DESC, chat_id DESC
            """
            with conn.cursor() as cur:
                cur.execute(query, (user_id,))
                rows = cur.fetchall()
        return [
            ChatModel(row["chat_id"], row["user_id"], row["updated_at"], row["title"])
            for row in rows
        ]

    @staticmethod
    def _normalize_paper_id(paper: PaperModel) -> Optional[int]:
        value = getattr(paper, "ID", None)
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
