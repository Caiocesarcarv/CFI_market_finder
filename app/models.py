"""Modelos Pydantic de entrada/saída da API."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class DataNature(str, Enum):
    """Natureza de qualquer número exibido pela plataforma.

    Toda resposta com dados comerciais (a partir da Fase 2) deve informar
    uma destas categorias, para o usuário nunca confundir dado real com
    estimativa ou exemplo.
    """

    REAL = "real"                    # obtido de fonte oficial (Comtrade, Comex Stat)
    ESTIMATIVA = "estimativa"        # calculado/projetado pela plataforma ou pela IA
    DEMONSTRATIVO = "demonstrativo"  # exemplo ilustrativo, sem valor analítico


class SearchCreate(BaseModel):
    product_name: str = Field(..., min_length=2, max_length=200, examples=["Café verde"])
    code: str = Field(..., min_length=2, max_length=20, examples=["0901.11.10"])


class Search(BaseModel):
    id: int
    product_name: str
    code_input: str
    code_digits: str
    code_type: str
    hs_code: str
    created_at: str
