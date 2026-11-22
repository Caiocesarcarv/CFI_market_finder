import os
import comtradeapicall
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("UNCOMTRADE_KEY")
PASTA_DESTINO = "./dados_comtrade_2025"
os.makedirs(PASTA_DESTINO, exist_ok=True)

# Gera a lista ['202501', '202502', ..., '202512']
meses_2025 = [f"2025{m:02d}" for m in range(1, 13)]

for periodo in meses_2025:
    print(f"Baixando bulk mensal de {periodo}...")

    comtradeapicall.bulkDownloadFinalFile(
        subscription_key=api_key,
        directory=PASTA_DESTINO,
        typeCode="C",
        freqCode="M",
        clCode="HS",
        period=periodo,
        reporterCode=None,
        decompress=True
    )