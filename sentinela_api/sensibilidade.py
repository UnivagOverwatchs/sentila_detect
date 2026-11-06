"""
sensibilidade.py - Traduz o controle "Sensibilidade" da tela de Configurações
nos limiares técnicos do detector de quedas.

Um único número (0.0 a 1.0) é mais fácil para o gestor do que 4 limiares.
Interpolação linear entre um perfil "menos alertas" (s=0) e "mais alertas" (s=1):

    parâmetro              s=0 (menos)   s=1 (mais)
    angulo_deitado (graus)     70            50     -> aceita tronco menos inclinado
    velocidade_queda           1.8           0.8    -> aceita descida mais lenta
    tempo_confirma_queda (s)   3.5           1.0    -> confirma mais rápido
    tempo_no_chao (s)          15            5
    desnivel_queda_lenta       1.0           0.5    -> aceita descida menor até o chão

Com s=0.65 (padrão "Alta (65%)" do protótipo) o resultado fica perto dos
valores padrão de config.py, que já foram validados nos testes.
"""

from sentinela_pose.config import ConfigQueda

# (valor com s=0, valor com s=1) para cada atributo de ConfigQueda.
_FAIXAS = {
    "angulo_deitado": (70.0, 50.0),
    "velocidade_queda": (1.8, 0.8),
    "tempo_confirma_queda": (3.5, 1.0),
    "tempo_no_chao": (15.0, 5.0),
    "desnivel_queda_lenta": (1.0, 0.5),
}


def aplicar_sensibilidade(cfg: ConfigQueda, sensibilidade: float) -> ConfigQueda:
    """
    Altera o objeto `cfg` NO LUGAR e o devolve.
    Alterar no lugar é proposital: as máquinas de estado guardam a mesma
    referência, então a mudança vale imediatamente, sem reiniciar a câmera.
    """
    s = min(max(float(sensibilidade), 0.0), 1.0)
    for atributo, (minimo, maximo) in _FAIXAS.items():
        setattr(cfg, atributo, round(minimo + (maximo - minimo) * s, 3))
    return cfg


def rotulo_sensibilidade(sensibilidade: float) -> str:
    """Texto exibido na interface (igual ao protótipo: 'Alta (65%)')."""
    pct = round(sensibilidade * 100)
    nivel = "Baixa" if pct < 34 else "Média" if pct < 60 else "Alta"
    return f"{nivel} ({pct}%)"
