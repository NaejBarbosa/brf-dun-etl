#!/usr/bin/env python3.13
# -*- coding: utf-8 -*-
"""
Nome: export_exclusivos_xlsx.py
Descrição: Exporta os produtos exclusivos BRF (cadastrados via scraping institucional)
           do SQLite para um arquivo Excel XLSX na pasta de downloads do Android.
"""

import os
import sqlite3
import subprocess
from openpyxl import Workbook

DB_PATH = '/root/projetos-scraping/scraping-brf/brf-dun/brf_produtos_b2b.db'
DOWNLOAD_DIR = '/sdcard/Download'
FILENAME = 'brf_produtos_exclusivos.xlsx'
OUTPUT_PATH = os.path.join(DOWNLOAD_DIR, FILENAME)

def clean_val(val, header):
    if val is None:
        return ""
    val_str = str(val).strip("'\"")
    if val_str.startswith("http://") or val_str.startswith("https://"):
        label = "Ver Imagem" if "image" in header.lower() else "Abrir Link"
        return f'=HYPERLINK("{val_str}", "{label}")'
    return val_str

def main():
    if not os.path.exists(DB_PATH):
        print(f"[!] Erro: Banco de dados SQLite não encontrado: {DB_PATH}")
        return
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    headers = [
        'sku', 'title', 'descrFiscal', 'ean', 'dun', 'marca', 'classe', 
        'conservacao', 'tempMin', 'tempMax', 'pesoLiquido', 'pesoBruto', 
        'vidaUtil', 'url', 'image_url'
    ]
    
    # Query selecionando os produtos cujo SKU começa com INST_ (novos institucionais)
    query = f"SELECT {', '.join(headers)} FROM produtos WHERE sku LIKE 'INST_%'"
    cursor.execute(query)
    rows = cursor.fetchall()
    
    if not rows:
        print("[!] Aviso: Nenhum produto exclusivo cadastrado no banco.")
        conn.close()
        return
        
    print(f"[*] Exportando {len(rows)} produtos exclusivos para XLSX...")
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Produtos Exclusivos"
    
    # Cabeçalho
    ws.append(headers)
    
    # Linhas de dados
    for row in rows:
        clean_row = []
        for i, cell in enumerate(row):
            header = headers[i]
            clean_row.append(clean_val(cell, header))
        ws.append(clean_row)
        
    wb.save(OUTPUT_PATH)
    print(f"[+] Planilha XLSX salva com sucesso em: {OUTPUT_PATH}")
    
    # Indexação no Android (Media Scan)
    try:
        subprocess.run(['termux-media-scan', OUTPUT_PATH], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[+] Indexação no Android realizada com sucesso!")
    except Exception as e:
        print(f"[!] Erro ao realizar o media-scan: {e}")
        
    conn.close()

if __name__ == '__main__':
    main()
