#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Nome: enriquecer_brf.py
Descrição: Script para extrair produtos e URLs de imagens dos sites oficiais
           Sadia e Perdigão, enriquecer o banco de dados SQLite brf_produtos_b2b.db,
           e cadastrar novos produtos inexistentes.
Autor: Antigravity - Engenheiro de Dados Sênior
"""

import os
import re
import sys
import time
import sqlite3
import requests
from bs4 import BeautifulSoup

DB_PATH = '/root/scraping/brf-dun/brf_produtos_b2b.db'
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
        
        # 2. Imagem do Produto
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

def main():
    if not os.path.exists(DB_PATH):
        print(f"[!] Banco de dados SQLite não encontrado no caminho: {DB_PATH}")
        sys.exit(1)
        
    init_db()
    
    sadia_urls = get_product_urls(SADIA_SITEMAP, "Sadia")
    perdigao_urls = get_product_urls(PERDIGAO_SITEMAP, "Perdigão")
    
    all_tasks = [(url, "Sadia") for url in sadia_urls] + [(url, "Perdigão") for url in perdigao_urls]
    total_tasks = len(all_tasks)
    
    print(f"\n[*] Total de {total_tasks} URLs para rastreamento e enriquecimento.")
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
                # O EAN já existe no banco. Atualiza a URL da imagem de todos os SKUs que usam esse EAN
                for sku, db_title in rows:
                    cursor.execute("""
                        UPDATE produtos 
                        SET image_url = ? 
                        WHERE sku = ?
                    """, (image_url, sku))
                conn.commit()
                updated_existing += 1
                continue
                
        # 2. Se o EAN não existe no banco (ou não foi extraído), tentamos buscar pelo título
        cursor.execute("SELECT sku FROM produtos WHERE title = ?", (title,))
        row_title = cursor.fetchone()
        if row_title:
            sku = row_title[0]
            cursor.execute("UPDATE produtos SET image_url = ?, ean = CASE WHEN ean IS NULL OR ean = '' THEN ? ELSE ean END WHERE sku = ?", (image_url, ean, sku))
            conn.commit()
            updated_existing += 1
            continue
            
        # 3. Se for um produto novo (EAN e Título não constam no banco), nós o cadastramos
        # Gera um SKU sequencial baseado no EAN ou um hash estável do título
        if ean:
            sku_novo = f"INST_{ean}"
        else:
            sku_novo = f"INST_H_{str(hash(title) & 0xffffffff)}"
            
        # Garante que o SKU seja único no banco
        cursor.execute("SELECT sku FROM produtos WHERE sku = ?", (sku_novo,))
        if cursor.fetchone():
            # SKU já cadastrado anteriormente, atualiza
            cursor.execute("UPDATE produtos SET image_url = ?, url = ? WHERE sku = ?", (image_url, url, sku_novo))
            conn.commit()
            updated_existing += 1
        else:
            # Insere novo produto institucional
            cursor.execute("""
                INSERT INTO produtos (
                    sku, title, descrFiscal, ean, dun, marca, classe, conservacao, tempMin, tempMax, pesoLiquido, pesoBruto, vidaUtil, url, image_url
                ) VALUES (
                    ?, ?, ?, ?, '', ?, 'Outros', 'Resfriado', '', '', '', '', '', ?, ?
                )
            """, (sku_novo, title, title, ean, marca, url, image_url))
            conn.commit()
            inserted_new += 1
            
        time.sleep(0.5) # Delay de cortesia para evitar sobrecarregar os servidores
        
    # Exporta os dados com imagens para JSON para que o pipeline Node.js processe as imagens
    cursor.execute("""
        SELECT sku, ean, dun, image_url 
        FROM produtos 
        WHERE image_url IS NOT NULL 
          AND image_url != '' 
          AND image_url != 'N/A'
    """)
    export_rows = cursor.fetchall()
    export_data = []
    for sku, ean, dun, image_url in export_rows:
        # Garante a limpeza de aspas e escolhe o código de barras
        sku = str(sku).strip('\'\"')
        ean = str(ean).strip('\'\"') if ean else ''
        dun = str(dun).strip('\'\"') if dun else ''
        image_url = str(image_url).strip('\'\"')
        
        barcode = ean if (ean and ean != 'N/A') else dun
        if not barcode or barcode == 'N/A':
            continue
            
        export_data.append({
            'sku': sku,
            'barcode': barcode,
            'image_url': image_url
        })
        
    json_path = '/root/scraping/brf-dun/dados_produtos_brf.json'
    import json
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)
    print(f"[INFO] Dados exportados para o pipeline Node.js ({len(export_data)} itens) em: {json_path}")
    
    conn.close()
    
    print("\n\n=============================================================")
    print("Enriquecimento Concluído!")
    print(f"Total de páginas analisadas: {processed}")
    print(f"Produtos B2B existentes enriquecidos com imagens: {updated_existing}")
    print(f"Novos produtos cadastrados no banco: {inserted_new}")
    print(f"Páginas sem correspondência ou com falha: {failed_or_skipped}")
    print("=============================================================\n")

if __name__ == '__main__':
    # Garante UTF-8 para exibição correta no console
    sys.stdout.reconfigure(encoding='utf-8')
    main()
