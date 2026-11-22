"""Dados FICTÍCIOS usados apenas nos testes (nunca exibidos pela aplicação)."""

from app.database import connect

NCM_ROWS = [
    ("09011110", "Café não torrado, não descafeinado, em grão", "TONELADA METRICA LIQUIDA"),
    ("09011190", "Café não torrado, não descafeinado, exceto em grão", "TONELADA METRICA LIQUIDA"),
    ("09012100", "Café torrado, não descafeinado", "QUILOGRAMA LIQUIDO"),
    ("12019000", "Soja, mesmo triturada, exceto para semeadura", "TONELADA METRICA LIQUIDA"),
]
COUNTRY_ROWS = [
    ("023", "Alemanha", "DEU", 276),
    ("025", "Alemanha Oriental", "DEU", 278),   # mesmo ISO3 (caso real do Comex Stat)
    ("249", "Estados Unidos", "USA", 840),
    ("873", "Wake, Ilha", "USA", 840),
    ("105", "Brasil", "BRA", 76),
    ("999", "Não Declarados", "ZZZ", 898),
]


def seed_reference(db_path):
    conn = connect(db_path)
    with conn:
        conn.executemany("INSERT INTO ncm VALUES (?,?,?)", NCM_ROWS)
        conn.execute("INSERT INTO ncm_fts (co_ncm, description) SELECT co_ncm, description FROM ncm")
        conn.executemany("INSERT INTO countries VALUES (?,?,?,?)", COUNTRY_ROWS)
    conn.close()


def comtrade_record(year, reporter_code, iso, name, partner_code, value):
    return {
        "refYear": year, "period": str(year), "flowCode": "M", "reporterCode": reporter_code,
        "reporterISO": iso, "reporterDesc": name, "partnerCode": partner_code,
        "primaryValue": value, "cifvalue": value, "fobvalue": None,
        "netWgt": value / 4, "qty": value / 4, "qtyUnitAbbr": "kg",
    }
