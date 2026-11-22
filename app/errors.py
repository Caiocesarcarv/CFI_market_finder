"""Erros de regra de negócio com mensagem pronta para o usuário."""


class AppError(Exception):
    """Erro previsto (código inválido, dado inexistente...). Vira JSON {"detail": ...}."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
