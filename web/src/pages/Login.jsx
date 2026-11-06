/*
 * Login.jsx - Tela de entrada. Só aparece quando o servidor exige login (LOGIN_OBRIGATORIO=1).
 * A sessão fica num cookie HttpOnly: esta tela nunca guarda senha nem token.
 */
import { useState } from "react";
import { IconeEscudo } from "../components/Icones.jsx";
import { api } from "../services/api.js";

export function Login({ aoEntrar }) {
  const [usuario, setUsuario] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState("");
  const [enviando, setEnviando] = useState(false);

  async function enviar(e) {
    e.preventDefault();
    setErro("");
    setEnviando(true);
    try {
      aoEntrar(await api.login(usuario.trim(), senha));
    } catch (falha) {
      setErro(typeof falha.detalhe === "string" ? falha.detalhe : "Não foi possível entrar. Confira a conexão.");
    } finally {
      setEnviando(false);
      setSenha("");
    }
  }

  return (
    <main className="login">
      <form className="cartao login__cartao" onSubmit={enviar}>
        <div className="login__marca">
          <IconeEscudo tamanho={26} />
          <h1>Sentinela</h1>
        </div>
        <p className="login__subtitulo">Entre para acompanhar os alertas</p>
        <label>
          Usuário
          <input
            autoFocus
            autoComplete="username"
            autoCapitalize="none"
            value={usuario}
            onChange={(e) => setUsuario(e.target.value)}
            required
          />
        </label>
        <label>
          Senha
          <input
            type="password"
            autoComplete="current-password"
            value={senha}
            onChange={(e) => setSenha(e.target.value)}
            required
          />
        </label>
        {erro && (
          <p className="erro" role="alert">
            {erro}
          </p>
        )}
        <button className="botao" type="submit" disabled={enviando || !usuario || !senha}>
          {enviando ? "Entrando..." : "Entrar"}
        </button>
      </form>
    </main>
  );
}
