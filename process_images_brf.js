#!/usr/bin/env node
// process_images_brf.js
// Script para download, redimensionamento e conversão de imagens em lote da BRF (Sadia e Perdigão)

const fs = require('fs');
const path = require('path');
const axios = require('axios');
const sharp = require('sharp');

// Configurações
const DATA_FILE = path.join(__dirname, 'dados_produtos_brf.json');
const OUTPUT_DIR = path.join(__dirname, 'imagens_preparadas');
const CONCURRENCY_LIMIT = 5; // Limite de concorrência para o Termux
const TIMEOUT_MS = 15000;    // Timeout de 15s

// Cria o diretório de saída se não existir
if (!fs.existsSync(OUTPUT_DIR)) {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
}

// Verifica se o arquivo de dados existe
if (!fs.existsSync(DATA_FILE)) {
  console.error(`[!] Erro: Arquivo de dados JSON da BRF não encontrado em: ${DATA_FILE}`);
  console.error(`[*] Execute primeiro: python3 enriquecer_brf.py`);
  process.exit(1);
}

// Carrega os dados dos produtos
const produtos = require(DATA_FILE);
console.log(`[*] Carregados ${produtos.length} produtos para processamento de imagens da BRF.`);
console.log(`[*] Imagens tratadas serão salvas em: ${OUTPUT_DIR}\n`);

/**
 * Realiza o download de uma imagem da internet e a processa utilizando o Sharp
 */
async function processarImagem(item, indice, total) {
  const nomeArquivo = `${item.barcode}.webp`;
  const caminhoDestino = path.join(OUTPUT_DIR, nomeArquivo);

  // Pula se a imagem já existir localmente
  if (fs.existsSync(caminhoDestino)) {
    console.log(`[${indice}/${total}] SKU: ${item.sku} | Código: ${item.barcode} | Já existe localmente. Pulando...`);
    return;
  }

  try {
    // 1. Download
    const response = await axios.get(item.image_url, {
      responseType: 'arraybuffer',
      timeout: TIMEOUT_MS,
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
        'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8'
      }
    });

    const buffer = Buffer.from(response.data);

    // 2. Processamento com Sharp
    await sharp(buffer)
      .resize({
        width: 400,
        fit: 'inside',
        withoutEnlargement: true
      })
      .webp({ quality: 80 })
      .toFile(caminhoDestino);

    console.log(`[${indice}/${total}] SKU: ${item.sku} | Código: ${item.barcode} | Imagem tratada e salva com sucesso.`);
  } catch (error) {
    let msgErro = error.message;
    if (error.response) {
      msgErro = `HTTP ${error.response.status}`;
    } else if (error.code === 'ECONNABORTED') {
      msgErro = 'Timeout de conexão';
    }
    console.error(`\x1b[31m[!] Erro no código ${item.barcode} (SKU: ${item.sku}): ${msgErro}\x1b[0m`);
  }
}

/**
 * Gerenciador de concorrência assíncrona
 */
async function executarFila() {
  let itemAtual = 0;
  const total = produtos.length;
  const tempoInicio = Date.now();

  async function trabalhador() {
    while (itemAtual < total) {
      const indice = itemAtual++;
      if (indice >= total) break;
      await processarImagem(produtos[indice], indice + 1, total);
    }
  }

  const trabalhadores = Array.from({ length: CONCURRENCY_LIMIT }, trabalhador);
  await Promise.all(trabalhadores);

  const tempoTotalMin = ((Date.now() - tempoInicio) / 1000 / 60).toFixed(2);
  console.log(`\n=============================================================`);
  console.log(`[*] Processamento de lote de imagens BRF finalizado!`);
  console.log(`[*] Tempo total gasto: ${tempoTotalMin} minutos.`);
  console.log(`[*] Veja os ficheiros em: ${OUTPUT_DIR}`);
  console.log(`=============================================================\n`);
}

// Inicia a execução
executarFila().catch(err => {
  console.error('[!] Falha crítica no processador:', err);
});
