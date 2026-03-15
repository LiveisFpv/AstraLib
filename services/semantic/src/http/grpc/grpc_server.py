import grpc
from concurrent import futures

from src.lib.logger import Logger
from src.http.grpc import service_pb2_grpc
from src.services.chat_service import ChatService
from src.services.ingestion.ingestion_service import IngestionService
from src.services.search.search_service import SearchService
from src.services.user_service import UserService
from src.http.grpc.grpc_handler import SemanticServiceHandlerGrpc


class SemanticServiceGrpc:
    def __init__(
        self,
        search_service: SearchService,
        chat_service: ChatService,
        user_service: UserService,
        logger: Logger,
        ingestion_service: IngestionService | None = None,
    ):
        self.logger = logger
        self.logger.info("Starting grpc server")
        self.search_service = search_service
        self.user_service = user_service
        self.chat_service = chat_service
        self.handler = SemanticServiceHandlerGrpc(
            search_service,
            chat_service,
            user_service,
            logger,
            ingestion_service,
        )

    def serve(self, port=50051):
        """Launch the gRPC server on the requested port."""
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        service_pb2_grpc.add_SemanticServiceServicer_to_server(self.handler, self.server)
        self.server.add_insecure_port(f"[::]:{port}")
        self.server.start()
        self.logger.info(f"Semantic service started on port: {port}")
        self.server.wait_for_termination()
        self.logger.info(f"Semantic service stoped on port: {port}")
