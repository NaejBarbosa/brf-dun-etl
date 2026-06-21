#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraper de Produtos BRF (Sadia e Perdigão) para centralmbrf.com.br
Ambiente de Execução: Termux (Android) - Leve, robusto e resiliente a quedas de rede.
Autor: Engenheiro de Dados Sênior (Automação Mobile & Web Scraping)
"""

import os
import re
import sys
import time
import sqlite3
import requests
from bs4 import BeautifulSoup

# Configurações Globais
DB_PATH = os.path.expanduser('~/scraping/brf-dun/brf_produtos_b2b.db')
SITEMAP_URL = 'https://centralmbrf.com.br/sitemap-product-1.xml'
USER_AGENT = 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'
HEADERS = {'User-Agent': USER_AGENT}
RETRY_DELAY = 15  # Segundos para aguardar caso a rede caia

def obter_conexao():
    """Retorna uma conexão ativa com o banco de dados SQLite."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    # Habilita suporte a chaves estrangeiras e otimizações de performance para gravação frequente
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")  # Write-Ahead Logging para robustez e concorrência
    return conn

def inicializar_banco():
    """Cria as tabelas necessárias no banco SQLite se não existirem."""
    conn = obter_conexao()
    cursor = conn.cursor()
    
    # 1. Tabela de Produtos (Estrutura Exata com SKU como Primary Key)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS produtos (
        sku TEXT PRIMARY KEY,
        title TEXT,
        descrFiscal TEXT,
        ean TEXT,
        dun TEXT,
        marca TEXT,
        classe TEXT,
        conservacao TEXT,
        tempMin TEXT,
        tempMax TEXT,
        pesoLiquido TEXT,
        pesoBruto TEXT,
        vidaUtil TEXT,
        url TEXT
    );
    """)
    
    # 2. Tabela Auxiliar de Controle de Fila (Resume State)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fila_urls (
        url TEXT PRIMARY KEY,
        status_processamento TEXT DEFAULT 'pendente'
    );
    """)
    
    conn.commit()
    conn.close()
    print("[INFO] Banco de dados SQLite inicializado com sucesso.")

def requisicao_com_retry(url):
    """
    Realiza uma requisição HTTP GET de forma robusta e persistente.
    Trata quedas de conexão, timeouts e aguarda reestabelecimento da rede.
    """
    while True:
        try:
            print(f"[REQUISICAO] Acessando: {url}")
            response = requests.get(url, headers=HEADERS, timeout=15)
            response.raise_for_status()
            return response.text
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            print(f"[AVISO] Rede offline ou instável: {e}")
            print(f"Aguardando {RETRY_DELAY} segundos para tentar novamente...")
            time.sleep(RETRY_DELAY)
        except requests.exceptions.HTTPError as e:
            # Erros HTTP como 404 (não encontrado) ou 500 não devem travar o loop de rede infinitamente
            status_code = e.response.status_code
            print(f"[ERRO HTTP] Falha HTTP {status_code} para a URL: {url}")
            if status_code in [404, 410]:
                return None  # Indica que a página de fato não existe
            # Para erros temporários do servidor (502, 503, 504), aguarda e tenta de novo
            print(f"Erro de servidor temporário. Aguardando {RETRY_DELAY} segundos...")
            time.sleep(RETRY_DELAY)
        except Exception as e:
            # Qualquer outro erro imprevisto
            print(f"[ERRO IMPREVISTO] Falha ao fazer requisição: {e}")
            print(f"Aguardando {RETRY_DELAY} segundos...")
            time.sleep(RETRY_DELAY)

def alimentar_fila_sitemap(force=False):
    """
    Baixa o sitemap de produtos e alimenta a fila_urls no banco SQLite.
    Se a fila já possuir links e force for False, ignora para poupar requisições.
    """
    conn = obter_conexao()
    cursor = conn.cursor()
    
    # Verifica se a fila já está populada
    cursor.execute("SELECT COUNT(*) FROM fila_urls")
    total_fila = cursor.fetchone()[0]
    
    if total_fila > 0 and not force:
        print(f"[INFO] Fila de URLs já contém {total_fila} links. Retomando processamento existente.")
        conn.close()
        return
        
    print("[INFO] Baixando sitemap para alimentar a fila de URLs...")
    xml_content = requisicao_com_retry(SITEMAP_URL)
    
    if not xml_content:
        print("[ERRO] Não foi possível baixar o sitemap.")
        conn.close()
        return
        
    # Extrai as URLs usando regex simples para evitar dependência de parseadores XML pesados
    urls = re.findall(r'<loc>(https://centralmbrf\.com\.br/product/[^<]+)</loc>', xml_content)
    
    if not urls:
        print("[AVISO] Nenhuma URL de produto encontrada no sitemap.")
        conn.close()
        return
        
    print(f"[INFO] Inserindo {len(urls)} URLs na fila_urls...")
    
    # Insere em lote usando INSERT OR IGNORE para evitar duplicar itens se o script for reiniciado
    cursor.executemany(
        "INSERT OR IGNORE INTO fila_urls (url, status_processamento) VALUES (?, 'pendente')",
        [(url,) for url in urls]
    )
    
    conn.commit()
    
    # Atualiza a contagem
    cursor.execute("SELECT COUNT(*) FROM fila_urls")
    total_fila = cursor.fetchone()[0]
    print(f"[INFO] Fila de URLs populada. Total na fila: {total_fila} links.")
    conn.close()

def clean_text(text):
    """Limpa e formata strings para armazenamento."""
    if not text:
        return ""
    # Remove múltiplos espaços, quebras de linha e caracteres invisíveis
    return re.sub(r'\s+', ' ', text).strip()

def inferir_classe(title, descr_fiscal):
    """
    Infere a classe/categoria do produto com base em regras heurísticas de palavras-chave.
    Baseado nas categorias padrão do portfólio BRF.
    """
    search_text = (title + " " + descr_fiscal).lower()
    
    aves_keywords = ["frango", "peru", "chester", "ave", "asa", "tulipa", "sassami", "peito", "drumette", "coxa", "sobrecoxa", "sambiquira", "moela"]
    suinos_keywords = ["suin", "pernil", "lombo", "panceta", "calabresa", "toscana", "bacon", "salame", "carre", "bisteca", "copa", "paio", "portuguesa"]
    bovinos_keywords = ["bovin", "alcatra", "contrafile", "costela", "cupim", "picanha", "miolo", "coxao", "patinho"]
    margarinas_keywords = ["margarina", "qualy", "deline"]
    lanches_keywords = ["pao de queijo", "lasanha", "fetuccini", "pizza", "hamburguer", "nuggets", "empanado"]
    
    # A ordem das verificações prioriza especificidades (ex: "picanha suína" deve ir para Suínos)
    if any(kw in search_text for kw in suinos_keywords):
        return "Suínos"
    elif any(kw in search_text for kw in aves_keywords):
        return "Aves"
    elif any(kw in search_text for kw in bovinos_keywords):
        return "Bovinos"
    elif any(kw in search_text for kw in margarinas_keywords):
        return "Margarinas"
    elif any(kw in search_text for kw in lanches_keywords):
        return "Lanches"
    return "Outros"

def inferir_conservacao(temp_max, search_text):
    """
    Infere o tipo de conservação do produto com base na temperatura máxima
    e em palavras-chave auxiliares.
    """
    if temp_max:
        # Extrai o valor numérico da temperatura máxima (ex: "-12°C" -> -12)
        num_match = re.search(r'(-?\d+)', temp_max)
        if num_match:
            val_max = int(num_match.group(1))
            if val_max <= -12:
                return "Congelado"
            elif val_max <= 10:
                return "Resfriado"
            else:
                return "Seco"
                
    # Fallback caso a temperatura não esteja explícita
    if "cong" in search_text or "empanado" in search_text or "hamburguer" in search_text:
        return "Congelado"
    elif "resf" in search_text or "cozido" in search_text or "presunto" in search_text or "salsicha" in search_text:
        return "Resfriado"
    return "Seco"

def parsear_produto(html, url):
    """
    Extrai os 14 campos da página HTML do produto usando BeautifulSoup e Regex.
    Retorna um dicionário com os campos ou None se for inválido.
    """
    soup = BeautifulSoup(html, 'html.parser')
    
    # 1. Title
    h1_tag = soup.find('h1')
    title = clean_text(h1_tag.text) if h1_tag else ""
    
    heading_comp = soup.find('commerce_product_details-heading')
    if not title and heading_comp:
        h1_heading = heading_comp.find('h1')
        if h1_heading:
            title = clean_text(h1_heading.text)
            
    # Se não encontrar título de forma alguma, a página não é um produto válido
    if not title:
        return None
        
    # 2. SKU e EAN
    sku = ""
    ean = ""
    if heading_comp:
        heading_text = heading_comp.get_text(" ")
        sku_match = re.search(r'C\u00f3digo do produto:\s*(\w+)', heading_text)
        if sku_match:
            sku = sku_match.group(1).strip()
        ean_match = re.search(r'C\u00f3digo de barras:\s*(\w+)', heading_text)
        if ean_match:
            ean = ean_match.group(1).strip()
            
    # Fallbacks de SKU/EAN no texto completo se não achar no heading
    if not sku:
        sku_match = re.search(r'C\u00f3digo do produto:\s*(\w+)', soup.get_text(" "))
        if sku_match:
            sku = sku_match.group(1).strip()
    if not ean:
        ean_match = re.search(r'C\u00f3digo de barras:\s*(\w+)', soup.get_text(" "))
        if ean_match:
            ean = ean_match.group(1).strip()

    # Se ainda assim não achar o SKU, usamos um hash da URL para não perder o registro (fallback extremo)
    if not sku:
        sku = "SKU_" + str(hash(url) & 0xffffffff)

    # 3. Marca
    marca = ""
    if heading_comp:
        field_displays = heading_comp.find_all('commerce-field-display')
        if field_displays:
            marca = clean_text(field_displays[0].text)
            
    # Fallback de marcas comuns da BRF baseado no título
    if not marca or marca.lower() not in ['sadia', 'perdig\u00e3o', 'qualy', 'deline']:
        if 'sadia' in title.lower():
            marca = 'Sadia'
        elif 'perdig' in title.lower():
            marca = 'Perdigão'
        elif 'qualy' in title.lower():
            marca = 'Qualy'
        elif 'deline' in title.lower():
            marca = 'Deline'
        else:
            marca = 'BRF'

    # 4. DescrFiscal
    descr_fiscal = ""
    details_comp = soup.find('c-b2b-single-product-details')
    if details_comp:
        # Acha a seção que inicia a descrição
        p_tags = details_comp.find_all('p')
        desc_title_tag = None
        for p in p_tags:
            if 'descri' in p.text.lower():
                desc_title_tag = p
                break
        if desc_title_tag:
            sibling = desc_title_tag.find_next_sibling()
            if sibling:
                descr_fiscal = clean_text(sibling.text)

    # Fallback para descrFiscal
    if not descr_fiscal:
        descr_fiscal = title  # Usa o título como descrição fiscal secundária

    # 5. Detalhes: Peso Líquido, Peso Bruto, Vida Útil
    peso_liquido = ""
    peso_bruto = ""
    vida_util = ""
    if details_comp:
        details_text = details_comp.get_text(" ")
        
        pl_match = re.search(r'Peso l\u00edquido\s*([\d\.,]+\s*[a-zA-Z]+)', details_text, re.IGNORECASE)
        if pl_match:
            peso_liquido = pl_match.group(1).strip()
            
        pb_match = re.search(r'Peso bruto\s*([\d\.,]+\s*[a-zA-Z]+)', details_text, re.IGNORECASE)
        if pb_match:
            peso_bruto = pb_match.group(1).strip()
            
        vu_match = re.search(r'([\d]+\s*Dia\(s\))\s*Vida \u00fatil', details_text, re.IGNORECASE)
        if vu_match:
            vida_util = vu_match.group(1).strip()
        else:
            vu_match = re.search(r'Vida \u00fatil\s*([\d]+\s*Dia\(s\))', details_text, re.IGNORECASE)
            if vu_match:
                vida_util = vu_match.group(1).strip()

    # 6. Informações de Conservação: Temp Mínima e Temp Máxima
    temp_min = ""
    temp_max = ""
    info_comp = soup.find('c-b2b-single-product-information')
    if info_comp:
        info_text = info_comp.get_text(" ")
        
        tmin_match = re.search(r'Temp\.\s*m\u00ednima\s*([-\d\.,]+\s*\u00b0C)', info_text, re.IGNORECASE)
        if tmin_match:
            temp_min = tmin_match.group(1).strip()
            
        tmax_match = re.search(r'Temp\.\s*m\u00e1xima\s*([-\d\.,]+\s*\u00b0C)', info_text, re.IGNORECASE)
        if tmax_match:
            temp_max = tmax_match.group(1).strip()

    # 7. DUN (Código de barras da caixa. Padrão vazio para o banco do scanner)
    dun = ""

    # 8. Classe (Categoria) e 9. Conservação (Heurísticas)
    classe = inferir_classe(title, descr_fiscal)
    conservacao = inferir_conservacao(temp_max, (title + " " + descr_fiscal).lower())

    return {
        "sku": sku,
        "title": title,
        "descrFiscal": descr_fiscal,
        "ean": ean,
        "dun": dun,
        "marca": marca,
        "classe": classe,
        "conservacao": conservacao,
        "tempMin": temp_min,
        "tempMax": temp_max,
        "pesoLiquido": peso_liquido,
        "pesoBruto": peso_bruto,
        "vidaUtil": vida_util,
        "url": url
    }

def processar_fila():
    """Processa as URLs da fila pendentes no banco SQLite."""
    conn = obter_conexao()
    cursor = conn.cursor()
    
    # Seleciona todas as URLs pendentes da fila
    cursor.execute("SELECT url FROM fila_urls WHERE status_processamento = 'pendente'")
    urls_pendentes = [row[0] for row in cursor.fetchall()]
    
    total_total = len(urls_pendentes)
    print(f"[INFO] Iniciando scraping de {total_total} URLs pendentes...")
    
    conn.close()  # Fecha a conexão inicial para abrir conexões locais durante o loop
    
    contador = 0
    for url in urls_pendentes:
        contador += 1
        
        # 1. Abre conexão específica para esta iteração (Resume State & Atomicidade)
        conn = obter_conexao()
        cursor = conn.cursor()
        
        try:
            # 2. Verifica se a URL já existe no banco de produtos (Resume State adicional)
            cursor.execute("SELECT sku FROM produtos WHERE url = ?", (url,))
            existe_produto = cursor.fetchone()
            if existe_produto:
                print(f"[{contador}/{total_total}] [PULADO] URL já cadastrada no banco de produtos: {url}")
                # Atualiza a fila e dá commit
                cursor.execute("UPDATE fila_urls SET status_processamento = 'processado' WHERE url = ?", (url,))
                conn.commit()
                conn.close()
                continue
            
            # 3. Faz o download da página (Wait & Retry robusto)
            html = requisicao_com_retry(url)
            if not html:
                # Página não encontrada (404/410). Marca como inválido e prossegue
                print(f"[{contador}/{total_total}] [INVALIDO] URL retornou 404: {url}")
                cursor.execute("UPDATE fila_urls SET status_processamento = 'invalido' WHERE url = ?", (url,))
                conn.commit()
                conn.close()
                continue
                
            # 4. Parse do HTML
            dados = parsear_produto(html, url)
            if not dados:
                print(f"[{contador}/{total_total}] [FALHA PARSE] Não foi possível parsear a página: {url}")
                cursor.execute("UPDATE fila_urls SET status_processamento = 'invalido' WHERE url = ?", (url,))
                conn.commit()
                conn.close()
                continue
                
            # 5. Inserção no banco em Tempo Real com INSERT OR IGNORE
            cursor.execute("""
            INSERT OR IGNORE INTO produtos (
                sku, title, descrFiscal, ean, dun, marca, classe, conservacao,
                tempMin, tempMax, pesoLiquido, pesoBruto, vidaUtil, url
            ) VALUES (
                :sku, :title, :descrFiscal, :ean, :dun, :marca, :classe, :conservacao,
                :tempMin, :tempMax, :pesoLiquido, :pesoBruto, :vidaUtil, :url
            );
            """, dados)
            
            # Atualiza status na fila_urls
            cursor.execute("UPDATE fila_urls SET status_processamento = 'processado' WHERE url = ?", (url,))
            
            # 6. Commit Imediato (Atomicidade) - Protege contra perda de dados
            conn.commit()
            print(f"[{contador}/{total_total}] [SALVO] SKU: {dados['sku']} | {dados['title']}")
            
        except Exception as e:
            print(f"[ERRO CRITICO] Erro ao processar URL {url}: {e}")
            # Em caso de qualquer falha no banco de dados, executa rollback para não deixar a transação travada
            try:
                conn.rollback()
            except:
                pass
        finally:
            conn.close()

def main():
    print("="*60)
    print("INICIANDO SCRAPER DE PRODUTOS BRF - PORTAL B2B")
    print("="*60)
    
    # 1. Inicializa o banco de dados e cria tabelas
    inicializar_banco()
    
    # 2. Alimenta a fila com as URLs do sitemap (Resume State)
    alimentar_fila_sitemap(force=False)
    
    # 3. Processa todos os itens pendentes da fila (Wait & Retry, Atomicidade)
    processar_fila()
    
    print("\n[INFO] Raspagem concluída.")
    
    # Mostra um relatório breve dos produtos salvos no banco
    conn = obter_conexao()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM produtos")
    total_produtos = cursor.fetchone()[0]
    cursor.execute("SELECT classe, COUNT(*) FROM produtos GROUP BY classe")
    classes = cursor.fetchall()
    
    print(f"Total de produtos salvos no SQLite: {total_produtos}")
    print("Por categoria/classe:")
    for c, count in classes:
        print(f"  - {c}: {count}")
    conn.close()

if __name__ == '__main__':
    # Garante suporte a UTF-8 no console do Termux
    sys.stdout.reconfigure(encoding='utf-8')
    main()
