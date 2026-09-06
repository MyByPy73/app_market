import csv
import io
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote
import pandas as pd
import requests
import streamlit as st

# Configuração da página
st.set_page_config(
    page_title="Comparador de Supermercados", page_icon="🛒", layout="wide"
)

session = requests.Session()
session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
        " like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
})

SUPERMERCADOS = {
    "Bistek": "https://www.bistek.com.br",
    "Giassi": "https://www.giassi.com.br",
    "Angeloni": "https://super.angeloni.com.br",
}

EXCLUSOES_POR_TERMO = {
    "açai": ["palmito", "sabonete", "shampoo", "refresco", "energético", "baly"],
    "queijo catupuri em lata": ["camembert"],
}


def extrair_peso_unidade(texto):
  texto_upper = texto.upper().replace(",", ".")
  padrao = r"(\d+(?:\.\d+)?)\s*(KG|G|GR|GMS|ML|L|LT|LITRO|LITROS|UN|UNID|UNIDADES)\b"
  match = re.search(padrao, texto_upper)

  if match:
    qtd = float(match.group(1))
    unidade = match.group(2)
    if unidade in ["G", "GR", "GMS"]:
      return qtd, "G"
    elif unidade in ["KG"]:
      return qtd, "KG"
    elif unidade in ["ML"]:
      return qtd, "ML"
    elif unidade in ["L", "LT", "LITRO", "LITROS"]:
      return qtd, "L"
    elif unidade in ["UN", "UNID", "UNIDADES"]:
      return qtd, "UN"

  return None, "INDETERMINADO"


def calcular_preco_padrao(preco, qtd, unidade):
  if not qtd or preco <= 0:
    return None
  if unidade in ["G", "ML"]:
    return (preco / qtd) * 1000
  elif unidade in ["KG", "L", "UN"]:
    return preco / qtd
  return None


def buscar_produtos_rede(nome_mercado, url_base, termo):
  termo_encoded = quote(termo)
  url = f"{url_base}/api/catalog_system/pub/products/search?ft={termo_encoded}&_from=0&_to=9"
  ofertas = []
  exclusoes = EXCLUSOES_POR_TERMO.get(termo.lower(), [])

  try:
    resposta = session.get(url, timeout=10)
    if resposta.status_code in [200, 206]:
      for p in resposta.json():
        nome_produto = p.get("productName", "")
        marca = p.get("brand", "")
        link = p.get("link", "")

        if any(exc in nome_produto.lower() for exc in exclusoes):
          continue

        for item in p.get("items", []):
          especificacao = item.get("nameComplete", item.get("name", ""))
          qtd, unidade = extrair_peso_unidade(especificacao)
          if unidade == "INDETERMINADO":
            qtd, unidade = extrair_peso_unidade(nome_produto)

          for seller in item.get("sellers", []):
            if seller.get("sellerId") == "1":
              oferta = seller.get("commertialOffer", {})
              preco = oferta.get("Price", 0)
              preco_de = oferta.get("ListPrice", 0)
              disponivel = oferta.get("IsAvailable", False)

              if disponivel and preco > 0:
                preco_padrao = calcular_preco_padrao(preco, qtd, unidade)
                ofertas.append({
                    "Supermercado": nome_mercado,
                    "TermoBusca": termo,
                    "NomeProduto": nome_produto,
                    "Especificacao": especificacao,
                    "Marca": marca,
                    "Quantidade": qtd if qtd else "N/A",
                    "Unidade": unidade,
                    "PrecoAtual": round(preco, 2),
                    "PrecoPorUnidadePadrao": (
                        round(preco_padrao, 2) if preco_padrao else "N/A"
                    ),
                    "PrecoAnterior": (
                        round(preco_de, 2) if preco_de > preco else "N/A"
                    ),
                    "EmPromocao": "SIM" if preco_de > preco else "NAO",
                    "Link": link,
                })
  except Exception:
    pass
  return ofertas


# Interface Gráfica Streamlit
st.title("🛒 Comparador de Preços de Supermercados")
st.write(
    "Digite os itens desejados (um por linha) e clique em buscar para comparar"
    " as ofertas."
)

texto_itens = st.text_area(
    "Lista de Compras:",
    height=150,
    placeholder="Exemplo:\naçai\nqueijo catupuri em lata\nleite integral",
)

if st.button("Buscar Produtos", type="primary"):
  itens = [
      linha.strip() for linha in texto_itens.split("\n") if linha.strip()
  ]

  if not itens:
    st.warning("Por favor, insira ao menos um item na lista.")
  else:
    dados_csv = []
    progresso = st.progress(0)
    st.info(f"Buscando {len(itens)} item(ns) nos supermercados...")

    with ThreadPoolExecutor(max_workers=10) as executor:
      tarefas = [
          executor.submit(buscar_produtos_rede, mercado, url, termo)
          for termo in itens
          for mercado, url in SUPERMERCADOS.items()
      ]

      concluidos = 0
      for future in as_completed(tarefas):
        resultado = future.result()
        if resultado:
          dados_csv.extend(resultado)
        concluidos += 1
        progresso.progress(concluidos / len(tarefas))

    if dados_csv:
      st.success(f"Encontrados {len(dados_csv)} resultados!")

      df = pd.DataFrame(dados_csv)
      st.dataframe(df, use_container_width=True)

      # Preparação do arquivo para download no formato com ';' e vírgula decimal
      df_export = df.copy()
      for col in ["PrecoAtual", "PrecoPorUnidadePadrao", "PrecoAnterior"]:
        df_export[col] = df_export[col].apply(
            lambda x: str(x).replace(".", ",")
            if isinstance(x, (int, float))
            else x
        )

      csv_buffer = io.StringIO()
      df_export.to_csv(csv_buffer, index=False, sep=";", encoding="utf-8-sig")

      st.download_button(
          label="📥 Baixar Resultado em CSV",
          data=csv_buffer.getvalue(),
          file_name="comparativo_supermercados.csv",
          mime="text/csv",
      )
    else:
      st.error("Nenhum produto foi encontrado para os termos informados.")
