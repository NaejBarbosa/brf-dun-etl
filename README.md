# BRF B2B - ETL de Códigos EAN & DUN 🚀

Este projeto consiste em uma solução de **ETL (Extract, Transform, Load)** desenvolvida em Python para extração de dados cadastrais (códigos de barras EAN e DUN) a partir de catálogos comerciais em formato PDF da BRF, com a posterior atualização e enriquecimento de uma base de dados local SQLite.

O projeto foi projetado e otimizado sob **arquitetura de recursos limitados**, visando execução suave em ambientes como **Termux ou Ubuntu sobre Android (mobile)**.

---

## 📌 Contexto & Objetivos

Muitas vezes, as bases de dados de produtos de e-commerce ou catálogos B2B possuem lacunas nos dados fiscais ou logísticos, como o **EAN-13** (código do produto para o consumidor) ou o **DUN-14** (código da caixa de embarque/distribuição).

Este script automatiza:
1. **Extração:** Leitura e processamento de documentos PDF comerciais da BRF página por página.
2. **Transformação:** Limpeza dos dados, validação estrita de integridade estrutural (tamanhos de dígitos) e pareamento por SKU.
3. **Carga:** Gravação das colunas ausentes (`ean` e `dun`) na base SQLite `brf_produtos_b2b.db`, otimizando a vida útil de memórias flash (I/O) e bateria do dispositivo móvel.

---

## ⚙️ Características de Arquitetura (Otimizações Mobile)

* **Leitura Otimizada de PDF (PyMuPDF):** Utiliza a biblioteca `fitz` (PyMuPDF), que é significativamente mais leve e rápida do que alternativas baseadas em Python puro, reduzindo o uso de CPU e RAM.
* **Processamento sob Demanda (Lazy Loading):** As páginas são carregadas na memória individualmente. Variáveis temporárias de texto e objetos de página são limpos de forma agressiva no final de cada loop e o coletor de lixo do Python (`gc.collect()`) é chamado a cada iteração para evitar vazamento de memória.
* **Extração Híbrida Inteligente:** 
  1. Primeiro tenta usar a detecção e extração de tabelas nativa do PyMuPDF (ideal para layouts tabulares e em grade do catálogo da BRF).
  2. Caso a página não possua tabelas ou a extração falhe, aciona um mecanismo de fallback baseado em máquina de estados e Regex no texto linear da página.
* **Otimização Estrita de Gravação (I/O e Bateria):** O script lê o banco de dados antes de efetuar qualquer escrita e apenas dispara queries de `UPDATE` se os campos `ean` ou `dun` estiverem de fato em branco. Isso minimiza escritas físicas na memória flash do celular.
* **Commits por Página (Atomicidade):** Salva as alterações a cada página processada para evitar perdas de dados em caso de interrupções (como falta de bateria) e liberar travas do banco SQLite rapidamente.

---

## 🗄️ Estrutura do Banco de Dados

A tabela principal atualizada pelo processo é a tabela `produtos`, contendo o seguinte esquema:

```sql
CREATE TABLE produtos (
    sku TEXT PRIMARY KEY,
    title TEXT,
    descrFiscal TEXT,
    ean TEXT,       -- Código de 13 dígitos (Consumidor)
    dun TEXT,       -- Código de 14 dígitos (Distribuição/Caixa)
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
```

---

## 🚀 Como Configurar e Executar

### 1. Pré-requisitos
Certifique-se de ter o Python 3 instalado no seu ambiente (Ubuntu/Termux) e instale o PyMuPDF:

```bash
# Instalação das dependências necessárias no Ubuntu/Debian
apt-get update && apt-get install -y python3-pip python3-fitz
```

### 2. Estrutura de Diretórios
O projeto espera que os arquivos de dados estejam localizados no seguinte layout:

```text
~/scraping/brf-dun/
├── atualizar_ean.py         # Script ETL de execução
├── catalogo_brf.pdf         # Catálogo comercial PDF da BRF
└── brf_produtos_b2b.db      # Banco de dados SQLite populado
```

### 3. Execução do Script
Para iniciar o pipeline de extração e gravação, execute:

```bash
python3 atualizar_ean.py
```

### 4. Formato do Log de Progresso (Terminal)
Durante o processamento, o script emitirá atualizações imediatas a cada página concluída:

```text
Conectando ao banco de dados: /root/scraping/brf-dun/brf_produtos_b2b.db
Abrindo catálogo PDF: /root/scraping/brf-dun/catalogo_brf.pdf
Catálogo possui 68 página(s). Iniciando processamento...
Página 1: 0 itens encontrados. 0 atualizados na base de dados.
Página 2: 0 itens encontrados. 0 atualizados na base de dados.
...
Página 5: 10 itens encontrados. 9 atualizados na base de dados.
Página 6: 8 itens encontrados. 8 atualizados na base de dados.
------------------------------------------------------------
Processamento concluído com sucesso!
Total de itens estruturalmente processados no PDF: 488
Total de registros atualizados (EAN e/ou DUN adicionados) no SQLite: 444
```

---

## 🛠️ Autores e Licença

Desenvolvido para automatização de processos logísticos e ETL comerciais.

* **Desenvolvedor:** NaejBarbosa
* **Licença:** MIT
