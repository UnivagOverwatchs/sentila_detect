// Copia os arquivos WASM do MediaPipe para public/mediapipe (servidos pelo nosso próprio site, sem CDN externa).
import { cpSync, mkdirSync } from "node:fs";
const origem = new URL("../node_modules/@mediapipe/tasks-vision/wasm/", import.meta.url);
const destino = new URL("../public/mediapipe/", import.meta.url);
mkdirSync(destino, { recursive: true });
cpSync(origem, destino, { recursive: true });
console.log("MediaPipe WASM copiado para public/mediapipe");
