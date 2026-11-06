/*
 * main.jsx - Ponto de entrada: carrega fontes (empacotadas, funcionam offline),
 * estilos e monta o App. O service worker é registrado automaticamente pelo
 * vite-plugin-pwa (registerType: "autoUpdate").
 */
import React from "react";
import ReactDOM from "react-dom/client";
import "@fontsource-variable/inter";
import "@fontsource/jetbrains-mono/400.css";
import "./styles.css";
import App from "./App.jsx";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
