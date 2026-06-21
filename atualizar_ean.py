#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script ETL para extração de códigos EAN e DUN do catálogo PDF da BRF e
atualização da base de dados SQLite.
Otimizado para execução em dispositivos mobile/ambientes com recursos limitados (Termux/Ubuntu no Android).
Atualiza a coluna 'ean' e a coluna 'dun' na base de dados SQLite quando estiverem vazias.
"""

import os
import sys
import re
import sqlite3
import gc
import fitz  # PyMuPDF, biblioteca de alta performance para processamento de PDF

# Configurações de Caminho
DB_PATH = os.path.expanduser("~/scraping/brf-dun/brf_produtos_b2b.db")
PDF_PATH = os.path.expanduser("~/scraping/brf-dun/catalogo_brf.pdf")

def limpar_campo(valor):
    """
    Remove espaços, quebras de linha e garante que o campo contenha apenas números.
    Regra 3: Tratamento de dados (.strip() e validação .isdigit()).
    """
    if valor is None:
        return ""
    valor_limpo = str(valor).strip().replace('\n', '').replace('\r', '')
    return valor_limpo if valor_limpo.isdigit() else ""

def atualizar_banco(cursor, sku, dun, ean):
    """
    Executa o UPDATE na tabela 'produtos' preenchendo o EAN e/ou o DUN se estiverem nulos ou vazios no banco.
    Regra 2 (adaptada): Atualiza ean e dun quando vazios, usando SKU ou DUN como âncora segura de busca.
    Evita match indesejado de strings vazias ou nulas ao ler e escrever no SQLite.
    """
    sku_val = sku if sku else None
    dun_val = dun if dun else None
    
    # Se não temos nenhuma âncora válida de busca para localizar o produto, aborta
    if not sku_val and not dun_val:
        return False
        
    res = None
    
    # 1. Busca o produto no banco pelo SKU
    if sku_val:
        cursor.execute("SELECT ean, dun, sku FROM produtos WHERE sku = ?", (sku_val,))
        res = cursor.fetchone()
        
    # 2. Se não encontrou pelo SKU, busca pelo DUN (caso o DUN seja válido)
    if not res and dun_val:
        cursor.execute("SELECT ean, dun, sku FROM produtos WHERE dun = ?", (dun_val,))
        res = cursor.fetchone()
        
    # Se o produto não existe no banco de dados, não fazemos nada
    if not res:
        return False
        
    ean_atual, dun_atual, sku_banco = res
    
    # Verifica o que de fato precisa ser atualizado para poupar bateria e I/O de disco
    atualizar_ean = ean and (not ean_atual or ean_atual.strip() == '')
    atualizar_dun = dun_val and (not dun_atual or dun_atual.strip() == '')
    
    if not atualizar_ean and not atualizar_dun:
        return False
        
    # Executa a query de atualização conforme a necessidade detectada
    if atualizar_ean and atualizar_dun:
        cursor.execute("UPDATE produtos SET ean = ?, dun = ? WHERE sku = ?", (ean, dun_val, sku_banco))
    elif atualizar_ean:
        cursor.execute("UPDATE produtos SET ean = ? WHERE sku = ?", (ean, sku_banco))
    elif atualizar_dun:
        cursor.execute("UPDATE produtos SET dun = ? WHERE sku = ?", (dun_val, sku_banco))
        
    return cursor.rowcount > 0

def extrair_de_tabelas(page):
    """
    Tenta extrair produtos usando o extrator de tabelas estruturadas do PyMuPDF.
    Ideal para páginas com layouts tabulares que agrupam dados em colunas.
    """
    encontrados = []
    try:
        tables = page.find_tables().tables
        for table in tables:
            data = table.extract()
            for row in data:
                if not row:
                    continue
                
                sku = None
                dun = None
                ean = None
                
                for cell in row:
                    if cell is None:
                        continue
                    
                    # Limpa a célula e confere se é numérica
                    cell_clean = limpar_campo(cell)
                    if not cell_clean:
                        continue
                    
                    length = len(cell_clean)
                    
                    # Identifica os campos baseados no comprimento
                    if length == 13:      # EAN-13
                        ean = cell_clean
                    elif length == 14:    # DUN-14
                        dun = cell_clean
                    elif 5 <= length <= 8:  # SKU
                        sku = cell_clean
                
                # Se encontramos dados associáveis, adicionamos à lista
                if ean or sku or dun:
                    encontrados.append({
                        "sku": sku,
                        "dun": dun,
                        "ean": ean
                    })
    except Exception:
        pass
    return encontrados

def extrair_de_texto_corrido(page):
    """
    Fallback usando análise linear do texto corrido quando a extração por tabelas falha
    ou não detecta nenhuma tabela na página.
    """
    encontrados = []
    text = page.get_text()
    lines = text.split("\n")
    
    pendente = {"sku": None, "dun": None, "ean": None}
    
    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue
            
        # Extrair todas as sequências numéricas da linha
        tokens = re.findall(r'\b\d+\b', line_clean)
        
        for token in tokens:
            length = len(token)
            
            if length == 13:  # EAN
                if pendente["ean"] and pendente["sku"]:
                    encontrados.append(pendente.copy())
                    pendente = {"sku": None, "dun": None, "ean": None}
                pendente["ean"] = token
            elif length == 14:  # DUN
                pendente["dun"] = token
            elif 5 <= length <= 8:  # SKU
                if pendente["sku"] and pendente["ean"]:
                    encontrados.append(pendente.copy())
                    pendente = {"sku": None, "dun": None, "ean": None}
                pendente["sku"] = token
                
    if pendente["ean"] and (pendente["sku"] or pendente["dun"]):
        encontrados.append(pendente.copy())
        
    return encontrados

def processar_catalogo():
    # Validações iniciais de existência de arquivos
    if not os.path.exists(PDF_PATH):
        print(f"Erro: O arquivo PDF não foi encontrado em '{PDF_PATH}'.")
        sys.exit(1)
        
    if not os.path.exists(DB_PATH):
        print(f"Erro: A base de dados SQLite não foi encontrada em '{DB_PATH}'.")
        sys.exit(1)
        
    print(f"Conectando ao banco de dados: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print(f"Abrindo catálogo PDF: {PDF_PATH}")
    try:
        doc = fitz.open(PDF_PATH)
    except Exception as e:
        print(f"Erro ao abrir o arquivo PDF: {e}")
        conn.close()
        sys.exit(1)
        
    total_paginas = len(doc)
    print(f"Catálogo possui {total_paginas} página(s). Iniciando processamento...")
    
    total_encontrados_geral = 0
    total_atualizados_geral = 0
    
    # Regra 1: Leitura página a página sem carregar todo o conteúdo na memória de uma vez
    for page_idx in range(total_paginas):
        page_num = page_idx + 1
        page = doc[page_idx]
        
        # Abordagem híbrida: Tenta extração de tabelas estruturadas primeiro
        encontrados_pagina = extrair_de_tabelas(page)
        
        # Se nenhuma tabela estruturada foi detectada, recorre ao parser de texto corrido
        if not encontrados_pagina:
            encontrados_pagina = extrair_de_texto_corrido(page)
            
        # Gravação no banco e contabilidade do progresso na página atual
        atualizados_pagina = 0
        encontrados_validos = 0
        
        for item in encontrados_pagina:
            sku_c = limpar_campo(item.get("sku"))
            dun_c = limpar_campo(item.get("dun"))
            ean_c = limpar_campo(item.get("ean"))
            
            # Regra 3: Validação estrutural de comprimentos
            # O EAN deve ter exatamente 13 dígitos para ser atualizado
            if ean_c and len(ean_c) != 13:
                ean_c = ""
                
            # O DUN, se fornecido, deve ter exatamente 14 dígitos
            if dun_c and len(dun_c) != 14:
                dun_c = ""
                
            # O SKU, se fornecido, deve ter entre 5 e 8 dígitos
            if sku_c and not (5 <= len(sku_c) <= 8):
                sku_c = ""
                
            # Se temos dados limpos de SKU/DUN para match
            if sku_c or dun_c:
                encontrados_validos += 1
                if atualizar_banco(cursor, sku_c, dun_c, ean_c):
                    atualizados_pagina += 1
                    
        # Regra 4: Commit logo após terminar de processar cada página
        conn.commit()
        
        # Regra 4: Log de progresso claro no terminal
        print(f"Página {page_num}: {encontrados_validos} itens encontrados. {atualizados_pagina} atualizados na base de dados.")
        
        total_encontrados_geral += encontrados_validos
        total_atualizados_geral += atualizados_pagina
        
        # Regra 1: Limpeza de variáveis locais e Garbage Collection para otimização mobile
        page = None
        encontrados_pagina = None
        gc.collect()
        
    doc.close()
    conn.close()
    
    print("-" * 60)
    print("Processamento concluído com sucesso!")
    print(f"Total de itens estruturalmente processados no PDF: {total_encontrados_geral}")
    print(f"Total de registros atualizados (EAN e/ou DUN adicionados) no SQLite: {total_atualizados_geral}")

if __name__ == "__main__":
    processar_catalogo()
