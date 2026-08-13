"""AI-assisted extraction of case materials into PROPOSED facts.

    document pages
        -> chunker.chunk_document()
        -> provider.extract()          candidates with a verbatim quote
        -> provenance.citations.resolve()   quote located in the stored page
        -> facts in PROPOSED status    for a human to verify or reject

The citation step is not advisory. A candidate whose quote is not in the
document does not become a fact.
"""

from .chunker import Chunk, chunk_document, split_page
from .prompts import PROMPT_VERSION, ExtractionRequest
from .provider import (
    Candidate,
    ExtractionError,
    ExtractionProvider,
    ExtractionResponse,
    PatternExtractor,
    get_extraction_provider,
)
from .service import ExtractionReport, extract_case, extract_document

__all__ = [
    "PROMPT_VERSION",
    "Candidate",
    "Chunk",
    "ExtractionError",
    "ExtractionProvider",
    "ExtractionReport",
    "ExtractionRequest",
    "ExtractionResponse",
    "PatternExtractor",
    "chunk_document",
    "extract_case",
    "extract_document",
    "get_extraction_provider",
    "split_page",
]
