#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Nome: enriquecer_brf.py
Descrição: Script para extrair produtos e URLs corretas de imagens dos sites oficiais
           Sadia e Perdigão (ou da Central BRF como fallback), enriquecer o banco 
           SQLite brf_produtos_b2b.db, e cadastrar novos produtos.
Autor: Antigravity - Engenheiro de Dados Sênior
"""

import os
import re
import sys
import time
import sqlite3
import requests
from bs4 import BeautifulSoup
import json

DB_PATH = '/root/projetos-scraping/scraping-brf/brf-dun/brf_produtos_b2b.db'
SADIA_SITEMAP = 'https://www.sadia.com.br/sitemap.xml'
PERDIGAO_SITEMAP = 'https://www.perdigao.com.br/sitemap.xml'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
}

def init_db():
    """Garante que a coluna image_url exista na tabela produtos."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(produtos)")
    cols = [col[1] for col in cursor.fetchall()]
    if 'image_url' not in cols:
        print("[*] Adicionando coluna 'image_url' na tabela 'produtos'...")
        cursor.execute("ALTER TABLE produtos ADD COLUMN image_url TEXT")
        conn.commit()
        print("[+] Coluna 'image_url' adicionada com sucesso.")
    else:
        print("[*] Coluna 'image_url' já existente no banco de dados.")
    conn.close()

def get_product_urls(sitemap_url, domain_name):
    """Obtém as URLs profundas de produtos (5+ subníveis) do sitemap."""
    print(f"[*] Baixando sitemap do {domain_name}...")
    try:
        res = requests.get(sitemap_url, headers=HEADERS, timeout=20)
        if res.status_code != 200:
            print(f"[!] Erro ao baixar sitemap do {domain_name}: HTTP {res.status_code}")
            return []
        
        urls = re.findall(r'<loc>([^<]+)</loc>', res.text)
        prod_urls = []
        for u in urls:
            if '/produtos/' in u:
                path = u.replace('https://', '')
                parts = [p for p in path.strip('/').split('/') if p]
                if len(parts) >= 5: # URL profunda de produto
                    prod_urls.append(u)
        print(f"[+] Total de {len(prod_urls)} URLs de produtos encontradas no sitemap do {domain_name}.")
        return prod_urls
    except Exception as e:
        print(f"[!] Erro ao obter sitemap do {domain_name}: {e}")
        return []

def clean_text(text):
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()

def process_product_page(url, marca):
    """Acessa a página do produto, extrai título, og:image e EAN."""
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        if res.status_code != 200:
            return None
            
        # Garante a decodificação UTF-8 correta para caracteres em português
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 1. Título do Produto
        og_title = soup.find('meta', property='og:title')
        title = og_title['content'] if og_title else ""
        if not title:
            title_tag = soup.find('title')
            title = title_tag.text if title_tag else ""
        title = clean_text(title)
        
        # Remove a marca no final do título institucional se houver
        title = re.sub(r'\s*-\s*(Sadia|Perdigão)\s*$', '', title, flags=re.IGNORECASE)
        title = clean_text(title)
        
        # 2. Imagem do Produto (Captura a imagem real do produto)
        image_url = ""
        if "sadia.com.br" in url:
            # Procura por tag img que contem '/products/' no src
            img_tag = soup.find('img', src=lambda x: x and '/products/' in x)
            if img_tag:
                image_url = img_tag.get('src')
        elif "perdigao.com.br" in url:
            # Procura primeiro a imagem oficial do produto dentro do figure.product-pack
            figure_tag = soup.find('figure', class_='product-pack')
            if figure_tag:
                img_tag = figure_tag.find('img')
                if img_tag:
                    image_url = img_tag.get('src')
            
            # Se nao encontrou, tenta por alt que contem 'imagem do produto:'
            if not image_url:
                img_tag = soup.find('img', alt=lambda x: x and 'imagem do produto:' in x.lower())
                if img_tag:
                    image_url = img_tag.get('src')
                
        # Se nao encontrou a imagem do produto pelos padroes refinados, usa o og:image como fallback
        if not image_url:
            og_image = soup.find('meta', property='og:image')
            image_url = og_image['content'] if og_image else ""
            
        # 3. EAN (Procura números de 13 dígitos no HTML que comecem com 789)
        eans = re.findall(r'\b789\d{10}\b', res.text)
        ean = eans[0] if eans else ""
        
        if not title or not image_url:
            return None
            
        return {
            'title': title,
            'image_url': image_url,
            'ean': ean,
            'marca': marca,
            'url': url
        }
    except Exception as e:
        print(f"  [!] Erro ao processar a página {url}: {e}")
        return None

def process_centralbrf_page(url):
    """Acessa a página do produto no portal Central BRF com User-Agent do Googlebot e extrai a imagem."""
    try:
        headers_bot = {
            'User-Agent': 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'
        }
        res = requests.get(url, headers=headers_bot, timeout=15)
        if res.status_code != 200:
            return None
            
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 1. Procura por tag img contendo 'blob.core.windows.net' e 'centralbrf' no src
        img_tag = soup.find('img', src=lambda x: x and 'blob.core.windows.net' in x and 'centralbrf' in x)
        if img_tag:
            return img_tag.get('src')
            
        # 2. Procura pela tag img principal do produto pelo alt contendo "Clique para expandir a imagem"
        img_tag_alt = soup.find('img', alt=lambda x: x and 'Clique para expandir a imagem' in x)
        if img_tag_alt:
            src = img_tag_alt.get('src')
            if src:
                if src.startswith('http'):
                    # Trata escapes e amp
                    src_clean = src.replace('&amp;', '&').replace('\\u003d', '=').replace('\\u0026', '&')
                    return src_clean
                elif src.startswith('/'):
                    # Link relativo (CMS Salesforce)
                    return f"https://centralmbrf.com.br{src}"
                    
        # 3. Procura por tag img contendo 'salesforce.com' e 'ImageServer' no src
        img_tag_sf = soup.find('img', src=lambda x: x and 'salesforce.com' in x and 'ImageServer' in x)
        if img_tag_sf:
            src = img_tag_sf.get('src')
            if src:
                src_clean = src.replace('&amp;', '&').replace('\\u003d', '=').replace('\\u0026', '&')
                return src_clean
            
        # Fallback: procura via regex no texto se nao achou a tag de imagem renderizada
        # Procurar tanto padrão blob/core.windows.net/centralbrf quanto salesforce.com/ImageServer
        matches = re.findall(r'(https://[^\s\"\']+(?:blob|core\.windows\.net|centralbrf|salesforce\.com[^\s\"\']*ImageServer)[^\s\"\']*)', res.text)
        if matches:
            # Filtra links com asterisco
            valid_matches = [m for m in matches if '*' not in m]
            cleaned_matches = []
            for m in valid_matches:
                m_clean = m.replace('&amp;', '&').replace('\\u003d', '=').replace('\\u0026', '&')
                # Valida se tem extensão típica de imagem ou se é o ImageServer
                if any(ext in m_clean.lower() for ext in ['.webp', '.png', '.jpg', '.jpeg']) or 'ImageServer' in m_clean:
                    cleaned_matches.append(m_clean)
            if cleaned_matches:
                webp_matches = [m for m in cleaned_matches if m.endswith('.webp')]
                return webp_matches[0] if webp_matches else cleaned_matches[0]
            
        return None
    except Exception as e:
        print(f"  [!] Erro ao processar página Central BRF {url}: {e}")
        return None

def main():
    if not os.path.exists(DB_PATH):
        print(f"[!] Banco de dados SQLite não encontrado no caminho: {DB_PATH}")
        sys.exit(1)
        
    init_db()
    
    # 0. Limpa as imagens antigas/erradas para repovoar o banco do zero
    print("[*] Esvaziando as URLs de imagens antigas da tabela 'produtos' no banco...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE produtos SET image_url = NULL")
    conn.commit()
    conn.close()
    print("[+] Coluna 'image_url' limpa com sucesso no banco de dados.")
    
    # 1. Scraping dos sites oficiais Sadia e Perdigão
    sadia_urls = get_product_urls(SADIA_SITEMAP, "Sadia")
    perdigao_urls = get_product_urls(PERDIGAO_SITEMAP, "Perdigão")
    
    all_tasks = [(url, "Sadia") for url in sadia_urls] + [(url, "Perdigão") for url in perdigao_urls]
    total_tasks = len(all_tasks)
    
    print(f"\n[*] Total de {total_tasks} URLs para rastreamento e enriquecimento (Sadia/Perdigão).")
    print("=============================================================")
    print("Iniciando scraping das páginas oficiais Sadia/Perdigão...")
    print("=============================================================\n")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    processed = 0
    updated_existing = 0
    inserted_new = 0
    failed_or_skipped = 0
    
    for url, marca in all_tasks:
        processed += 1
        sys.stdout.write(f"\rProcessando [{processed}/{total_tasks}] | Sucessos: {updated_existing + inserted_new}...")
        sys.stdout.flush()
        
        data = process_product_page(url, marca)
        if not data:
            failed_or_skipped += 1
            continue
            
        ean = data['ean']
        image_url = data['image_url']
        title = data['title']
        
        # 1. Tenta atualizar produtos existentes que possuem esse EAN no banco
        if ean:
            cursor.execute("SELECT sku, title FROM produtos WHERE ean = ?", (ean,))
            rows = cursor.fetchall()
            
            if rows:
                for sku, db_title in rows:
                    cursor.execute("""
                        UPDATE produtos 
                        SET image_url = ? 
                        WHERE sku = ?
                    """, (image_url, sku))
                conn.commit()
                updated_existing += 1
                continue
                
        # 2. Se o EAN não existe, busca pelo título
        cursor.execute("SELECT sku FROM produtos WHERE title = ?", (title,))
        row_title = cursor.fetchone()
        if row_title:
            sku = row_title[0]
            cursor.execute("UPDATE produtos SET image_url = ?, ean = CASE WHEN ean IS NULL OR ean = '' THEN ? ELSE ean END WHERE sku = ?", (image_url, ean, sku))
            conn.commit()
            updated_existing += 1
            continue
            
        # 3. Insere produto novo institucional
        if ean:
            sku_novo = f"INST_{ean}"
        else:
            sku_novo = f"INST_H_{str(hash(title) & 0xffffffff)}"
            
        cursor.execute("SELECT sku FROM produtos WHERE sku = ?", (sku_novo,))
        if cursor.fetchone():
            cursor.execute("UPDATE produtos SET image_url = ?, url = ? WHERE sku = ?", (image_url, url, sku_novo))
            conn.commit()
            updated_existing += 1
        else:
            cursor.execute("""
                INSERT INTO produtos (
                    sku, title, descrFiscal, ean, dun, marca, classe, conservacao, tempMin, tempMax, pesoLiquido, pesoBruto, vidaUtil, url, image_url
                ) VALUES (
                    ?, ?, ?, ?, '', ?, 'Outros', 'Resfriado', '', '', '', '', '', ?, ?
                )
            """, (sku_novo, title, title, ean, marca, url, image_url))
            conn.commit()
            inserted_new += 1
            
        time.sleep(0.5)
        
    print(f"\n\n[+] Fim da etapa Sadia/Perdigão. Sucessos: {updated_existing + inserted_new} itens.")
    print("=============================================================")
    print("Iniciando busca no portal Central BRF para itens pendentes...")
    print("=============================================================\n")
    
    # 2. Buscar no portal Central BRF os produtos que continuam sem imagem
    cursor.execute("""
        SELECT sku, url, title, ean, dun 
        FROM produtos 
        WHERE (image_url IS NULL OR image_url = '' OR image_url = 'N/A' OR image_url LIKE '%brfsacoeintgrcprd%')
          AND url LIKE 'https://centralmbrf.com.br/product/%'
    """)
    pending_central = cursor.fetchall()
    total_pending_central = len(pending_central)
    print(f"[*] Total de produtos sem imagem pendentes da Central BRF: {total_pending_central}")
    
    central_success = 0
    central_fail = 0
    central_processed = 0
    
    for sku, product_url, title, ean, dun in pending_central:
        central_processed += 1
        sys.stdout.write(f"\rProcessando Central BRF [{central_processed}/{total_pending_central}] | Sucessos: {central_success}...")
        sys.stdout.flush()
        
        img_url_central = process_centralbrf_page(product_url)
        
        # Se a imagem for invalida (CSP com asterisco ou host antigo), limpamos ela
        if img_url_central and ('*' in img_url_central or 'brfsacoeintgrcprd' in img_url_central):
            img_url_central = None
            
        # Fallback de Produção B2B (tenta obter a URL previsivel do blob ativo se tiver EAN/DUN)
        if not img_url_central:
            barcode = ean or dun
            if barcode and barcode != 'N/A':
                barcode_clean = str(barcode).strip('\'\"')
                potential_url = f"https://brfsaprodutosprd.blob.core.windows.net/centralbrf/B2B_Product_Photos/{barcode_clean}_1_1_1000_72_RGB.webp"
                try:
                    head_res = requests.head(potential_url, headers=HEADERS, timeout=5)
                    if head_res.status_code == 200:
                        img_url_central = potential_url
                except Exception:
                    pass
        
        if img_url_central:
            cursor.execute("""
                UPDATE produtos 
                SET image_url = ? 
                WHERE sku = ?
            """, (img_url_central, sku))
            conn.commit()
            central_success += 1
        else:
            cursor.execute("""
                UPDATE produtos 
                SET image_url = 'N/A' 
                WHERE sku = ?
            """, (sku,))
            conn.commit()
            central_fail += 1
            
        time.sleep(0.5)
        
    # 3. Exporta os dados para o JSON do pipeline Node.js
    cursor.execute("""
        SELECT sku, ean, dun, image_url 
        FROM produtos 
        WHERE image_url IS NOT NULL 
          AND image_url != '' 
          AND image_url != 'N/A'
    """)
    export_rows = cursor.fetchall()
    export_data = []
    for sku_exp, ean_exp, dun_exp, img_exp in export_rows:
        sku_exp = str(sku_exp).strip('\'\"')
        ean_exp = str(ean_exp).strip('\'\"') if ean_exp else ''
        dun_exp = str(dun_exp).strip('\'\"') if dun_exp else ''
        img_exp = str(img_exp).strip('\'\"')
        
        barcode = ean_exp if (ean_exp and ean_exp != 'N/A') else dun_exp
        if not barcode or barcode == 'N/A':
            continue
            
        export_data.append({
            'sku': sku_exp,
            'barcode': barcode,
            'image_url': img_exp
        })
        
    json_path = '/root/projetos-scraping/scraping-brf/brf-dun/dados_produtos_brf.json'
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)
    print(f"\n[INFO] Dados exportados para o pipeline Node.js ({len(export_data)} itens) em: {json_path}")
    
    conn.close()
    
    print("\n\n=============================================================")
    print("Processo de Enriquecimento BRF Finalizado com Sucesso!")
    print(f"Total Sadia/Perdigão Rastreados: {processed}")
    print(f"  - Atualizados: {updated_existing}")
    print(f"  - Novos cadastrados: {inserted_new}")
    print(f"Total Central BRF Processados: {central_processed}")
    print(f"  - Imagens vinculadas: {central_success}")
    print(f"  - Falhas/Sem Imagem: {central_fail}")
    print("=============================================================\n")

if __name__ == '__main__':
    # Garante UTF-8 para exibição correta no console
    sys.stdout.reconfigure(encoding='utf-8')
    main()
