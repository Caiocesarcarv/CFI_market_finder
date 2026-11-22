"""Validação e normalização de códigos HS (Sistema Harmonizado) e NCM.

- HS: 2 (capítulo), 4 (posição) ou 6 (subposição) dígitos — padrão internacional,
  usado pela UN Comtrade.
- NCM: 8 dígitos — padrão Mercosul, usado pelo Comex Stat. Os 6 primeiros
  dígitos da NCM correspondem à subposição HS6.

Esta validação é apenas estrutural (formato e capítulo existente). Ela não
garante que o código exista na nomenclatura vigente; isso será conferido
contra as tabelas oficiais nas próximas fases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SEPARATORS = re.compile(r"[\s.\-/]")
_CODE_TYPES = {2: "HS2", 4: "HS4", 6: "HS6", 8: "NCM"}


class InvalidCodeError(ValueError):
    """Código HS/NCM com formato inválido."""


@dataclass(frozen=True)
class ClassifiedCode:
    code_input: str   # como digitado (sem espaços nas pontas)
    code_digits: str  # somente dígitos
    code_type: str    # HS2 | HS4 | HS6 | NCM
    hs_code: str      # código HS para consultas internacionais (máx. 6 dígitos)


def classify_code(raw: str) -> ClassifiedCode:
    """Normaliza um código HS/NCM e identifica seu tipo.

    Aceita separadores comuns: "0901.11.10", "0901-11", "09 01".
    """
    code_input = (raw or "").strip()
    digits = _SEPARATORS.sub("", code_input)

    if not digits:
        raise InvalidCodeError("Informe um código HS ou NCM.")
    if not digits.isdigit():
        raise InvalidCodeError("O código deve conter apenas números (pontos e hífens são aceitos).")
    if len(digits) not in _CODE_TYPES:
        raise InvalidCodeError(
            "O código deve ter 2, 4 ou 6 dígitos (HS) ou 8 dígitos (NCM); "
            f"foram informados {len(digits)}."
        )

    chapter = int(digits[:2])
    # Capítulos 01–97 do SH; o 77 é reservado e não é utilizado.
    if not 1 <= chapter <= 97 or chapter == 77:
        raise InvalidCodeError(f"Capítulo {digits[:2]} não existe no Sistema Harmonizado.")

    return ClassifiedCode(
        code_input=code_input,
        code_digits=digits,
        code_type=_CODE_TYPES[len(digits)],
        hs_code=digits[:6],
    )
