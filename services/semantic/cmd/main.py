import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.al_models.e5.encoder import EncoderConfig, SemanticEncoder
from src.config.config import (
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_LORA_PATH,
    EMBEDDING_MODEL_NAME,
    FAISS_DOC_IDS_PATH,
    FAISS_INDEX_PATH,
    LOG_LEVEL,
    LOGSTASH_HOST,
    LOGSTASH_PORT,
    SEMANTIC_PORT,
)
from src.http.grpc.grpc_server import SemanticServiceGrpc
from src.lib.logger import Logger
from src.services.chat_service import ChatService
from src.services.ingestion.ingestion_service import IngestionService
from src.services.ingestion.openalex_client import OpenAlexClient
from src.services.ingestion.scheduler import IngestionScheduler
from src.services.ingestion.settings import IngestionSettings
from src.services.ingestion.weighted_index import maybe_create_weighted_index_manager
from src.services.search.faiss_index import FaissIndex
from src.services.search.faiss_searcher import FaissSearcher
from src.services.search.search_service import SearchService
from src.storage.citation_repository import CitationRepository
from src.services.user_service import UserService
from src.storage.chat_repository import ChatRepository
from src.storage.ingestion_repository import IngestionRepository
from src.storage.paper_ingestion_repository import PaperIngestionRepository
from src.storage.paper_repository import PaperRepository
from src.storage.user_repository import UserRepository


def main() -> None:
    logger = Logger(LOGSTASH_HOST, LOGSTASH_PORT, "Semantic_Search_Service", LOG_LEVEL)

    encoder_cfg = EncoderConfig(
        model_name=EMBEDDING_MODEL_NAME,
        batch_size=EMBEDDING_BATCH_SIZE,
        lora_path=EMBEDDING_LORA_PATH,
    )
    encoder = SemanticEncoder(encoder_cfg)
    index = FaissIndex(
        index_path=FAISS_INDEX_PATH,
        doc_ids_path=FAISS_DOC_IDS_PATH,
        dimension=encoder.output_dim,
    )
    paper_repository = PaperRepository()
    searcher = FaissSearcher(encoder, index, paper_repository)
    search_service = SearchService(searcher)

    ingestion_settings = IngestionSettings()
    ingestion_repository = IngestionRepository()
    citation_repository = CitationRepository()
    paper_ingestion_repository = PaperIngestionRepository(citation_repository=citation_repository)
    weighted_index_manager = maybe_create_weighted_index_manager(
        index=index,
        encoder=encoder,
        citation_repository=citation_repository,
        logger=logger,
        required=ingestion_settings.weighted_runtime_required,
    )
    openalex_client = OpenAlexClient(ingestion_settings) if ingestion_settings.openalex_enabled else None
    ingestion_service = IngestionService(
        queue_repository=ingestion_repository,
        paper_repository=paper_ingestion_repository,
        encoder=encoder,
        index=index,
        settings=ingestion_settings,
        logger=logger,
        openalex_client=openalex_client,
        weighted_index_manager=weighted_index_manager,
    )
    ingestion_scheduler = IngestionScheduler(
        service=ingestion_service,
        settings=ingestion_settings,
        logger=logger,
    )
    ingestion_scheduler.start()

    # ! TODO services, connections and repoes
    user_repo = UserRepository()
    chat_repo = ChatRepository()
    user_service = UserService(user_repo)
    chat_service = ChatService(chat_repo, user_service)

    service = SemanticServiceGrpc(
        search_service,
        chat_service,
        user_service,
        logger,
        ingestion_service,
    )
    try:
        service.serve(SEMANTIC_PORT)
    finally:
        ingestion_scheduler.stop()
        ingestion_service.close()


if __name__ == "__main__":
    main()
