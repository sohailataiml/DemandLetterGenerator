from __future__ import annotations

from fastapi import Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..domain.models import Case, Demand, Fact, SourceDocument


def get_case(
    case_id: str = Path(..., description="Case identifier"),
    db: Session = Depends(get_db),
) -> Case:
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"case {case_id} not found")
    return case


def get_demand(
    demand_id: str = Path(..., description="Demand identifier"),
    db: Session = Depends(get_db),
) -> Demand:
    demand = db.get(Demand, demand_id)
    if demand is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"demand {demand_id} not found"
        )
    return demand


def get_document(
    document_id: str = Path(..., description="Document identifier"),
    db: Session = Depends(get_db),
) -> SourceDocument:
    document = db.get(SourceDocument, document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"document {document_id} not found"
        )
    return document


def get_fact(
    fact_id: str = Path(..., description="Fact identifier"),
    db: Session = Depends(get_db),
) -> Fact:
    fact = db.get(Fact, fact_id)
    if fact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"fact {fact_id} not found")
    return fact
