#!/usr/bin/env python3
"""Load cleaned OpenAlex datasets into Postgres."""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union

import polars as pl
from psycopg import Connection
from psycopg.rows import Row

from src.db.connection import get_connection
from src.storage.citation_repository import CitationRepository


LOGGER = logging.getLogger("openalex_loader")
PIPE_SEPARATOR = " | "


def split_pipe(value: Optional[str]) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(PIPE_SEPARATOR)]
    else:
        parts = [str(part).strip() for part in value]
    return [part for part in parts if part]


def split_author_name(full_name: str) -> Tuple[str, str, Optional[str]]:
    tokens = full_name.strip().split()
    if not tokens:
        return "Unknown", "Unknown", None
    if len(tokens) == 1:
        return tokens[0], tokens[0], None
    if len(tokens) == 2:
        return tokens[0], tokens[1], None
    first = tokens[0]
    last = tokens[-1]
    middle = " ".join(tokens[1:-1]) or None
    return first, last, middle


def extract_authors(row: dict) -> List[dict]:
    ids = split_pipe(row.get("authors_ids"))
    names = split_pipe(row.get("authors_names"))
    orcids = split_pipe(row.get("authors_orcids"))
    max_len = max(len(ids), len(names), len(orcids), 0)
    authors: List[dict] = []
    for idx in range(max_len):
        name = names[idx] if idx < len(names) else ""
        orcid_raw = orcids[idx] if idx < len(orcids) else ""
        openalex_id = ids[idx] if idx < len(ids) else ""
        name = (name or "").strip()
        orcid = (orcid_raw or "").strip().lower() or None
        openalex_id = (openalex_id or "").strip()
        if not name and not orcid and not openalex_id:
            continue
        first, last, middle = split_author_name(name or "Unknown")
        authors.append(
            {
                "display": name,
                "first": first,
                "last": last,
                "middle": middle,
                "orcid": orcid,
            }
        )
    return authors


def extract_institutions(row: dict) -> List[dict]:
    names = split_pipe(row.get("institutions_names"))
    countries = split_pipe(row.get("institutions_country_codes"))
    max_len = max(len(names), len(countries), 0)
    institutions: List[dict] = []
    for idx in range(max_len):
        name = names[idx] if idx < len(names) else ""
        if not name:
            continue
        country = countries[idx] if idx < len(countries) else ""
        institutions.append(
            {
                "name": name.strip(),
                "country": country.strip() or None,
            }
        )
    return institutions


def extract_relations(row: dict) -> Tuple[List[str], List[str]]:
    referenced = split_pipe(row.get("referenced_works"))
    related = split_pipe(row.get("related_works"))
    return referenced, related


def extract_locations(row: dict) -> List[dict]:
    locations: List[dict] = []

    def push_location(prefix: str, label: str) -> None:
        landing = clean_text(row.get(f"{prefix}_landing_page_url"))
        pdf = clean_text(row.get(f"{prefix}_pdf_url"))
        license_value = clean_text(row.get(f"{prefix}_license"))
        source_type = clean_text(row.get(f"{prefix}_source_type"))
        is_oa_raw = str(row.get(f"{prefix}_is_oa") or "").strip().lower()
        version_value = license_value or source_type
        if not version_value:
            if is_oa_raw in {"true", "1", "yes"}:
                version_value = "open_access"
            else:
                version_value = "unspecified"

        if landing:
            locations.append(
                {
                    "url": landing,
                    "link_type": f"{label}_landing",
                    "version": version_value,
                }
            )
        if pdf and pdf != landing:
            locations.append(
                {
                    "url": pdf,
                    "link_type": f"{label}_pdf",
                    "version": version_value,
                }
            )

    push_location("primary_loc", "primary")
    push_location("best_oa_loc", "best_oa")
    return locations


@dataclass
class RowData:
    identifier_aliases: List[str]
    title: Optional[str]
    abstract: Optional[str]
    year: Optional[int]
    type_value: Optional[str]
    created_at: Optional[dt.datetime]
    doi: Optional[str]
    authors: List[dict]
    institutions: List[dict]
    locations: List[dict]
    referenced_ids: List[str]
    related_ids: List[str]
    paper_id: Optional[int] = None
    is_existing: bool = False
    seed_paper_ids: Set[int] = field(default_factory=set)


def process_batch(context: LoaderContext, rows: List[RowData]) -> None:
    if not rows:
        return

    conn = context.conn

    identifier_pool: List[str] = []
    for row in rows:
        identifier_pool.extend(row.identifier_aliases)
    if identifier_pool:
        context.fetch_paper_ids(identifier_pool)

    for row in rows:
        row.paper_id = None
        row.is_existing = False
        for identifier in row.identifier_aliases:
            paper_id = context.paper_id_cache.get(identifier)
            if paper_id is not None:
                row.paper_id = paper_id
                row.is_existing = True
                break

    new_rows = [row for row in rows if row.paper_id is None]
    if new_rows:
        insert_values: List[Tuple[Optional[int], Optional[str], Optional[str], Optional[int], Optional[str], dt.datetime]] = []
        for row in new_rows:
            created_at = row.created_at or dt.datetime.utcnow()
            row.created_at = created_at
            insert_values.append((None, row.title, row.abstract, row.year, row.type_value, created_at))
        insert_sql = """
            INSERT INTO papers (created_by_user_id, title, abstract, year, state, created_at)
            VALUES %s
            RETURNING paper_id
        """
        with conn.cursor() as cur:
            inserted = execute_values(cur, insert_sql, insert_values, fetch=True)
        for row, inserted_row in zip(new_rows, inserted):
            row.paper_id = inserted_row["paper_id"]
            row.is_existing = False

    existing_rows = [row for row in rows if row.is_existing]
    if existing_rows:
        update_values = [
            (row.paper_id, row.title, row.abstract, row.year, row.type_value, row.created_at)
            for row in existing_rows
        ]
        update_sql = """
            UPDATE papers AS p
            SET title = data.title,
                abstract = data.abstract,
                year = data.year,
                state = data.state,
                created_at = COALESCE(data.created_at, p.created_at)
            FROM (VALUES %s) AS data(paper_id, title, abstract, year, state, created_at)
            WHERE p.paper_id = data.paper_id
        """
        with conn.cursor() as cur:
            execute_values(cur, update_sql, update_values)

    for row in rows:
        if row.paper_id is not None:
            context.register_paper_identifiers(row.paper_id, row.identifier_aliases)

    openalex_pairs = {
        (row.paper_id, identifier)
        for row in rows
        if row.paper_id is not None
        for identifier in row.identifier_aliases
        if identifier
    }
    if openalex_pairs:
        insert_sql = """
            INSERT INTO paper_identifiers (paper_id, identifier_type_id, identifier)
            VALUES %s
            ON CONFLICT DO NOTHING
        """
        values = [(pid, context.openalex_type_id, identifier) for pid, identifier in openalex_pairs]
        with conn.cursor() as cur:
            execute_values(cur, insert_sql, values)

    doi_pairs = {
        (row.paper_id, row.doi.lower())
        for row in rows
        if row.paper_id is not None and row.doi
    }
    if doi_pairs:
        insert_sql = """
            INSERT INTO paper_identifiers (paper_id, identifier_type_id, identifier)
            VALUES %s
            ON CONFLICT DO NOTHING
        """
        values = [(pid, context.doi_type_id, doi) for pid, doi in doi_pairs]
        with conn.cursor() as cur:
            execute_values(cur, insert_sql, values)

    author_map: Dict[Tuple[str, str], dict] = {}
    author_entries: List[Tuple[int, int, Tuple[str, str]]] = []
    for row in rows:
        if row.paper_id is None:
            continue
        for order, author in enumerate(row.authors, start=1):
            key = context.make_author_key(author)
            author_map.setdefault(key, author)
            author_entries.append((row.paper_id, order, key))

    author_ids = context.resolve_authors(author_map)
    paper_author_orders: Dict[Tuple[int, int], int] = {}
    for paper_id, order, key in author_entries:
        author_id = author_ids.get(key)
        if not author_id:
            continue
        current = paper_author_orders.get((paper_id, author_id))
        if current is None or order < current:
            paper_author_orders[(paper_id, author_id)] = order

    if paper_author_orders:
        insert_sql = """
            INSERT INTO paper_authors (paper_id, author_id, author_order)
            VALUES %s
            ON CONFLICT (paper_id, author_id) DO UPDATE
                SET author_order = EXCLUDED.author_order
        """
        values = [
            (paper_id, author_id, order)
            for (paper_id, author_id), order in paper_author_orders.items()
        ]
        with conn.cursor() as cur:
            execute_values(cur, insert_sql, values)

    institution_map: Dict[str, dict] = {}
    institution_entries: List[Tuple[int, str]] = []
    for row in rows:
        if row.paper_id is None:
            continue
        for institution in row.institutions:
            key = context.make_institution_key(institution)
            if not key.strip("|"):
                continue
            institution_map.setdefault(key, institution)
            institution_entries.append((row.paper_id, key))

    institution_ids = context.resolve_institutions(institution_map)
    paper_institutions: Set[Tuple[int, int]] = set()
    for paper_id, key in institution_entries:
        institution_id = institution_ids.get(key)
        if institution_id:
            paper_institutions.add((paper_id, institution_id))

    if paper_institutions:
        insert_sql = """
            INSERT INTO paper_institutions (institution_id, paper_id)
            VALUES %s
            ON CONFLICT DO NOTHING
        """
        values = [(institution_id, paper_id) for paper_id, institution_id in paper_institutions]
        with conn.cursor() as cur:
            execute_values(cur, insert_sql, values)

    location_candidates: Dict[Tuple[int, str, str, str], Tuple[int, str, str, str]] = {}
    for row in rows:
        if row.paper_id is None:
            continue
        for location in row.locations:
            url = (location.get("url") or "").strip()
            if not url:
                continue
            link_type = (location.get("link_type") or "").strip()
            version = (location.get("version") or "").strip()
            key = (row.paper_id, url, link_type, version)
            location_candidates.setdefault(key, key)

    if location_candidates:
        paper_ids = list({item[0] for item in location_candidates.values()})
        existing: Dict[int, Set[Tuple[str, str, str]]] = defaultdict(set)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT paper_id,
                       url,
                       COALESCE(link_type, '') AS link_type,
                       COALESCE(version, '') AS version
                FROM locations
                WHERE paper_id = ANY(%s)
                """,
                (paper_ids,),
            )
            for row_db in cur.fetchall():
                existing[row_db["paper_id"]].add(
                    (row_db["url"], row_db["link_type"], row_db["version"])
                )

        to_insert: List[Tuple[int, str, Optional[str], Optional[str]]] = []
        seen_new: Set[Tuple[int, str, str, str]] = set()
        for paper_id, url, link_type, version in location_candidates.values():
            key = (url, link_type, version)
            if key in existing[paper_id] or (paper_id, url, link_type, version) in seen_new:
                continue
            seen_new.add((paper_id, url, link_type, version))
            to_insert.append(
                (
                    paper_id,
                    url,
                    link_type or None,
                    version or None,
                )
            )

        if to_insert:
            insert_sql = """
                INSERT INTO locations (paper_id, url, link_type, version)
                VALUES %s
            """
            with conn.cursor() as cur:
                execute_values(cur, insert_sql, to_insert)

    for row in rows:
        if row.paper_id is None:
            continue

        row.seed_paper_ids.add(int(row.paper_id))
        row.seed_paper_ids.update(
            context.resolve_pending_citations_for_identifiers(
                row.paper_id,
                identifier_type_id=context.openalex_type_id,
                identifiers=row.identifier_aliases,
            )
        )

        desired_citation_dest_ids: set[int] = set()
        pending_citation_identifiers: set[tuple[int, str]] = set()
        for identifier in row.referenced_ids:
            cleaned = (identifier or "").strip()
            if not cleaned:
                continue
            aliases = [cleaned]
            normalized = normalize_openalex_id(cleaned)
            if normalized:
                aliases.insert(0, normalized)
            aliases = [value for value in dict.fromkeys(value for value in aliases if value)]

            dest_paper_id = context.lookup_paper_id(aliases)
            if dest_paper_id is not None and int(dest_paper_id) != int(row.paper_id):
                desired_citation_dest_ids.add(int(dest_paper_id))
            else:
                for alias in aliases:
                    pending_citation_identifiers.add((context.openalex_type_id, alias))

        citation_sync = context.citation_repository.replace_outgoing_citations(
            conn,
            src_paper_id=int(row.paper_id),
            resolved_dest_ids=desired_citation_dest_ids,
            pending_identifiers=pending_citation_identifiers,
        )
        row.seed_paper_ids.update(citation_sync.seed_paper_ids)
        row.seed_paper_ids.update(citation_sync.resolved_pending_sources)

        desired_related_dest_ids: set[int] = set()
        for identifier in row.related_ids:
            cleaned = (identifier or "").strip()
            if not cleaned:
                continue
            aliases = [cleaned]
            normalized = normalize_openalex_id(cleaned)
            if normalized:
                aliases.insert(0, normalized)
            aliases = [value for value in dict.fromkeys(value for value in aliases if value)]

            dest_paper_id = context.lookup_paper_id(aliases)
            if dest_paper_id is not None and int(dest_paper_id) != int(row.paper_id):
                desired_related_dest_ids.add(int(dest_paper_id))

        context.citation_repository.sync_related_edges(
            conn,
            src_paper_id=int(row.paper_id),
            related_dest_ids=desired_related_dest_ids,
        )
OPENALEX_PREFIX_RE = re.compile(r"^https?://(?:www\.)?openalex\.org/", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load OpenAlex parquet chunks into Postgres")
    parser.add_argument(
        "--parquet",
        action="append",
        help="Path to a cleaned parquet file (can be supplied multiple times)",
    )
    parser.add_argument(
        "--indir",
        help="Directory containing cleaned parquet files (will read *.parquet)",
    )
    parser.add_argument("--limit", type=int, help="Limit number of records processed")
    parser.add_argument(
        "--log-level",
        default=os.getenv("LOG_LEVEL", "INFO"),
        help="Logging level (default taken from LOG_LEVEL env)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=int(os.getenv("LOAD_BATCH_SIZE", "5000")),
        help="Number of rows to process before committing (default 500)",
    )
    return parser.parse_args()


def list_parquet_files(args: argparse.Namespace) -> list[Path]:
    files: set[Path] = set()
    if args.parquet:
        for p in args.parquet:
            files.add(Path(p).resolve())
    if args.indir:
        for p in Path(args.indir).glob("*.parquet"):
            files.add(p.resolve())
    return sorted(files)


def ensure_identifier_type(conn: Connection, name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO identifier_types (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
            (name,),
        )
        cur.execute(
            "SELECT identifier_type_id FROM identifier_types WHERE name = %s",
            (name,),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError(f"Failed to retrieve identifier type for '{name}'")
        return row["identifier_type_id"]


def normalize_openalex_id(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return OPENALEX_PREFIX_RE.sub("", text)


def find_paper_by_identifier(
    conn: Connection, identifier_type_id: int, identifier: Union[str, Iterable[str]]
) -> Optional[int]:
    if isinstance(identifier, str):
        identifiers = [identifier]
    else:
        identifiers = [str(item).strip() for item in identifier if item is not None]

    identifiers = [value for value in dict.fromkeys(identifiers) if value]
    if not identifiers:
        return None

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT paper_id
            FROM paper_identifiers
            WHERE identifier_type_id = %s AND identifier = ANY(%s)
            LIMIT 1
            """,
            (identifier_type_id, identifiers),
        )
        row: Optional[Row] = cur.fetchone()
        return row["paper_id"] if row else None


def upsert_paper(
    conn: Connection,
    *,
    paper_id: Optional[int],
    title: Optional[str],
    abstract: Optional[str],
    year: Optional[int],
    type_value: Optional[str],
    created_at: Optional[dt.datetime],
    created_by_user_id: Optional[int] = None,
) -> int:
    created_at = created_at or dt.datetime.utcnow()
    with conn.cursor() as cur:
        if paper_id is None:
            cur.execute(
                """
                INSERT INTO papers (created_by_user_id, title, abstract, year, state, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING paper_id
                """,
                (created_by_user_id, title, abstract, year, type_value, created_at),
            )
            return cur.fetchone()["paper_id"]

        cur.execute(
            """
            UPDATE papers
            SET title = %s,
                abstract = %s,
                year = %s,
                state = %s,
                created_at = COALESCE(%s, created_at),
                created_by_user_id = COALESCE(created_by_user_id, %s)
            WHERE paper_id = %s
            """,
            (title, abstract, year, type_value, created_at, created_by_user_id, paper_id),
        )
        return paper_id


def link_identifier(conn: Connection, paper_id: int, identifier_type_id: int, identifier: str) -> None:
    if not identifier:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO paper_identifiers (paper_id, identifier_type_id, identifier)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (paper_id, identifier_type_id, identifier),
        )


def execute_values(
    cur,
    sql: str,
    data: Iterable[Sequence[Any]],
    *,
    fetch: bool = False,
    page_size: Optional[int] = None,
):
    records = [tuple(row) for row in data]
    if not records:
        return [] if fetch else None

    row_length = len(records[0]) or 1
    max_params = 65535
    max_chunk = max(1, max_params // row_length)
    if page_size is not None:
        max_chunk = max(1, min(max_chunk, page_size))

    results = []
    for start in range(0, len(records), max_chunk):
        chunk = records[start : start + max_chunk]
        placeholders = ", ".join(
            "(" + ", ".join(["%s"] * row_length) + ")"
            for _ in chunk
        )
        query = sql.replace("%s", placeholders, 1)
        params: List[Any] = [value for record in chunk for value in record]
        cur.execute(query, params)
        if fetch:
            results.extend(cur.fetchall())
    if fetch:
        return results
    return None


class LoaderContext:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn
        self.openalex_type_id = ensure_identifier_type(conn, "openalex")
        self.doi_type_id = ensure_identifier_type(conn, "doi")
        self.citation_repository = CitationRepository()
        self.author_by_orcid: Dict[str, int] = {}
        self.author_by_name: Dict[str, int] = {}
        self.institution_by_key: Dict[str, int] = {}
        self.paper_id_cache: Dict[str, int] = {}
        self.relations_buffer: Set[Tuple[int, int]] = set()
        self.pending_relations: Dict[str, List[Tuple[int, bool]]] = defaultdict(list)
        self.location_cache: Dict[int, Set[Tuple[str, str, str]]] = {}
        self.institution_by_name = self.institution_by_key

    def register_paper_identifiers(self, paper_id: int, identifiers: Iterable[str]) -> None:
        keys: set[str] = set()
        for identifier in identifiers:
            if not identifier:
                continue
            cleaned = identifier.strip()
            if not cleaned:
                continue
            keys.add(cleaned)
            normalized = normalize_openalex_id(cleaned)
            if normalized:
                keys.add(normalized)
        for key in keys:
            self.paper_id_cache[key] = paper_id
        for key in keys:
            self._resolve_pending_key(key, paper_id)

    def resolve_pending_citations_for_identifiers(
        self,
        paper_id: int,
        *,
        identifier_type_id: int,
        identifiers: Iterable[str],
    ) -> set[int]:
        return self.citation_repository.resolve_pending_for_identifiers(
            self.conn,
            paper_id=paper_id,
            identifier_type_id=identifier_type_id,
            identifiers=identifiers,
        )

    def _resolve_pending_key(self, identifier: str, paper_id: int) -> None:
        pending = self.pending_relations.pop(identifier, [])
        for src_id, bidirectional in pending:
            self.queue_relation(src_id, paper_id, bidirectional)

    def fetch_paper_ids(self, identifiers: Iterable[str]) -> Dict[str, int]:
        result: Dict[str, int] = {}
        missing: List[str] = []
        for identifier in identifiers:
            if not identifier:
                continue
            cleaned = identifier.strip()
            if not cleaned:
                continue
            if cleaned in self.paper_id_cache:
                result[cleaned] = self.paper_id_cache[cleaned]
            else:
                missing.append(cleaned)
        if missing:
            unique_missing = list(dict.fromkeys(missing))
            if unique_missing:
                chunk_size = 1000
                with self.conn.cursor() as cur:
                    for start in range(0, len(unique_missing), chunk_size):
                        chunk = unique_missing[start : start + chunk_size]
                        cur.execute(
                            """
                            SELECT identifier, paper_id
                            FROM paper_identifiers
                            WHERE identifier_type_id = %s
                              AND identifier = ANY(%s)
                            """,
                            (self.openalex_type_id, chunk),
                        )
                        for row in cur.fetchall():
                            identifier = row["identifier"]
                            paper_id = row["paper_id"]
                            self.paper_id_cache[identifier] = paper_id
                            result[identifier] = paper_id
        return result

    def lookup_paper_id(self, identifiers: Iterable[str]) -> Optional[int]:
        lookup_candidates = []
        for identifier in identifiers:
            if not identifier:
                continue
            cleaned = identifier.strip()
            if not cleaned:
                continue
            normalized = normalize_openalex_id(cleaned)
            if normalized:
                lookup_candidates.append(normalized)
            lookup_candidates.append(cleaned)
        if not lookup_candidates:
            return None
        mapping = self.fetch_paper_ids(lookup_candidates)
        if mapping:
            return next(iter(mapping.values()))
        return None

    def queue_relation(self, src_paper_id: int, dst_paper_id: int, bidirectional: bool) -> None:
        if src_paper_id == dst_paper_id:
            return
        self.relations_buffer.add((src_paper_id, dst_paper_id))
        if bidirectional:
            self.relations_buffer.add((dst_paper_id, src_paper_id))

    def resolve_pending_from_map(self, mapping: Dict[str, int]) -> None:
        for identifier, paper_id in mapping.items():
            self.paper_id_cache[identifier] = paper_id
            self._resolve_pending_key(identifier, paper_id)

    def flush_pending_relations(self) -> None:
        if not self.pending_relations:
            return
        identifiers = list(dict.fromkeys(self.pending_relations.keys()))
        mapping = self.fetch_paper_ids(identifiers)
        for identifier, paper_id in mapping.items():
            self._resolve_pending_key(identifier, paper_id)

    def flush_relations(self) -> None:
        if not self.relations_buffer:
            return
        data = list(self.relations_buffer)
        with self.conn.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO paper_relations (src_paper_id, dst_paper_id)
                VALUES %s
                ON CONFLICT DO NOTHING
                """,
                data,
            )
        self.relations_buffer.clear()

    @staticmethod
    def make_author_key(author: dict) -> Tuple[str, str]:
        orcid = (author.get("orcid") or "").lower()
        if orcid:
            return ("orcid", orcid)
        first = (author.get("first") or "").lower()
        last = (author.get("last") or "").lower()
        middle = (author.get("middle") or "").lower()
        return ("name", f"{first}|{last}|{middle}")

    def resolve_authors(self, authors: Dict[Tuple[str, str], dict]) -> Dict[Tuple[str, str], int]:
        if not authors:
            return {}

        result: Dict[Tuple[str, str], int] = {}
        orcid_lookup: List[str] = []
        name_lookup: List[str] = []

        for key in authors.keys():
            kind, value = key
            if kind == "orcid":
                if value in self.author_by_orcid:
                    result[key] = self.author_by_orcid[value]
                else:
                    orcid_lookup.append(value)
            else:
                if value in self.author_by_name:
                    result[key] = self.author_by_name[value]
                else:
                    name_lookup.append(value)

        with self.conn.cursor() as cur:
            if orcid_lookup:
                cur.execute(
                    """
                    SELECT author_id, lower(orcid) AS orcid
                    FROM authors
                    WHERE lower(orcid) = ANY(%s)
                    """,
                    (orcid_lookup,),
                )
                for row in cur.fetchall():
                    key = ("orcid", row["orcid"])
                    author_id = row["author_id"]
                    self.author_by_orcid[row["orcid"]] = author_id
                    result[key] = author_id

            if name_lookup:
                cur.execute(
                    """
                    SELECT author_id,
                           lower(first_name) AS first,
                           lower(last_name) AS last,
                           COALESCE(lower(middle_name), '') AS middle
                    FROM authors
                    WHERE orcid IS NULL
                      AND (lower(first_name) || '|' || lower(last_name) || '|' || COALESCE(lower(middle_name), '')) = ANY(%s)
                    """,
                    (name_lookup,),
                )
                for row in cur.fetchall():
                    name_key = f"{row['first']}|{row['last']}|{row['middle']}"
                    author_id = row["author_id"]
                    self.author_by_name[name_key] = author_id
                    result[("name", name_key)] = author_id

        to_insert: List[Tuple[Tuple[str, str], dict]] = [
            (key, data) for key, data in authors.items() if key not in result
        ]
        if not to_insert:
            return result

        insert_values = [
            (
                data.get("first"),
                data.get("last"),
                data.get("middle"),
                data.get("orcid"),
            )
            for _, data in to_insert
        ]
        insert_sql = """
            INSERT INTO authors (first_name, last_name, middle_name, orcid)
            VALUES %s
            ON CONFLICT (orcid) DO UPDATE
                SET first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    middle_name = EXCLUDED.middle_name
            RETURNING author_id,
                      lower(first_name) AS first,
                      lower(last_name) AS last,
                      COALESCE(lower(middle_name), '') AS middle,
                      COALESCE(lower(orcid), '') AS orcid
        """
        with self.conn.cursor() as cur:
            rows = execute_values(cur, insert_sql, insert_values, fetch=True)

        for (key, _), row in zip(to_insert, rows):
            author_id = row["author_id"]
            if key[0] == "orcid":
                self.author_by_orcid[key[1]] = author_id
            else:
                self.author_by_name[key[1]] = author_id
            result[key] = author_id

        return result

    @staticmethod
    def make_institution_key(institution: dict) -> str:
        name = (institution.get("name") or "").lower()
        country = (institution.get("country") or "").lower()
        return f"{name}|{country}"

    def resolve_institutions(self, institutions: Dict[str, dict]) -> Dict[str, int]:
        if not institutions:
            return {}

        result: Dict[str, int] = {}
        lookup: List[str] = []
        for key in institutions.keys():
            if key in self.institution_by_key:
                result[key] = self.institution_by_key[key]
            else:
                lookup.append(key)

        if lookup:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT institution_id,
                           lower(name) AS name,
                           COALESCE(lower(country), '') AS country
                    FROM institutions
                    WHERE (lower(name) || '|' || COALESCE(lower(country), '')) = ANY(%s)
                    """,
                    (lookup,),
                )
                for row in cur.fetchall():
                    key = f"{row['name']}|{row['country']}"
                    institution_id = row["institution_id"]
                    self.institution_by_key[key] = institution_id
                    result[key] = institution_id

        to_insert = [(key, data) for key, data in institutions.items() if key not in result]
        if not to_insert:
            return result

        insert_values = [
            (
                data.get("name"),
                data.get("country"),
            )
            for _, data in to_insert
        ]
        insert_sql = """
            INSERT INTO institutions (name, country)
            VALUES %s
            RETURNING institution_id,
                      lower(name) AS name,
                      COALESCE(lower(country), '') AS country
        """
        with self.conn.cursor() as cur:
            rows = execute_values(cur, insert_sql, insert_values, fetch=True)

        for (key, _), row in zip(to_insert, rows):
            key_normalized = f"{row['name']}|{row['country']}"
            institution_id = row["institution_id"]
            self.institution_by_key[key_normalized] = institution_id
            result[key] = institution_id

        return result
def parse_publication_date(value: Optional[Union[str, dt.date, dt.datetime]]) -> Optional[dt.datetime]:
    if not value:
        return None
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.datetime.min.time())
    if not isinstance(value, str):
        return None
    try:
        normalized = value.strip()
        if not normalized:
            return None
        normalized = normalized.replace("Z", "")
        return dt.datetime.fromisoformat(normalized)
    except ValueError:
        return None


def load_records(
    conn: Connection,
    frame: pl.DataFrame,
    *,
    context: LoaderContext,
    limit: Optional[int] = None,
    batch_size: int = 500,
) -> int:
    processed = 0
    batch: List[RowData] = []
    for row in frame.iter_rows(named=True):
        if limit is not None and processed >= limit:
            break

        raw_openalex_id = (row.get("id") or "").strip()
        if not raw_openalex_id:
            continue

        normalized_openalex_id = normalize_openalex_id(raw_openalex_id)
        identifier_aliases: List[str] = []
        if normalized_openalex_id:
            identifier_aliases.append(normalized_openalex_id)
        identifier_aliases.append(raw_openalex_id)
        identifier_aliases = [value for value in dict.fromkeys(identifier_aliases) if value]

        title = clean_text(row.get("title"))
        abstract = clean_text(row.get("abstract_text"))
        if not title and not abstract:
            continue

        year = row.get("publication_year")
        if isinstance(year, float):
            year = int(year)
        elif year is not None:
            try:
                year = int(year)
            except (TypeError, ValueError):
                year = None

        publication_date = parse_publication_date(row.get("publication_date"))
        type_value = clean_text(row.get("type")) or None

        doi_value = clean_text(row.get("doi"))
        doi_normalized = doi_value.lower() if doi_value else None

        authors = extract_authors(row)
        institutions = extract_institutions(row)
        locations = extract_locations(row)
        referenced_ids, related_ids = extract_relations(row)

        batch.append(
            RowData(
                identifier_aliases=identifier_aliases,
                title=title or None,
                abstract=abstract or None,
                year=year,
                type_value=type_value,
                created_at=publication_date,
                doi=doi_normalized,
                authors=authors,
                institutions=institutions,
                locations=locations,
                referenced_ids=referenced_ids,
                related_ids=related_ids,
            )
        )

        processed += 1
        if processed % 500 == 0:
            LOGGER.info("Processed %s records", processed)

        if len(batch) >= batch_size:
            process_batch(context, batch)
            conn.commit()
            batch.clear()

    if batch:
        process_batch(context, batch)
        conn.commit()
        batch.clear()

    return processed


def clean_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def load_file(
    conn: Connection,
    path: Path,
    *,
    context: LoaderContext,
    limit: Optional[int] = None,
    batch_size: int = 500,
) -> int:
    LOGGER.info("Loading %s", path)
    frame = pl.read_parquet(path)
    loaded = load_records(conn, frame, context=context, limit=limit, batch_size=batch_size)
    LOGGER.info("Loaded %s rows from %s", loaded, path)
    return loaded


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    files = list_parquet_files(args)
    if not files:
        raise SystemExit("No parquet files provided")

    total = 0
    with get_connection() as conn:
        context = LoaderContext(conn)
        for file_path in files:
            total += load_file(
                conn,
                file_path,
                context=context,
                limit=args.limit,
                batch_size=args.batch_size,
            )
        conn.commit()

    LOGGER.info("Total records processed: %s", total)


if __name__ == "__main__":
    main()
