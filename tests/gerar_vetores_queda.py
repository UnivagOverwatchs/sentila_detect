"""
gerar_vetores_queda.py - Gera web/tests/vetores_queda.json: cenários de pose + o que o detector Python respondeu
quadro a quadro. O teste em JavaScript (web/tests/detectorQueda.test.js) roda os MESMOS cenários e exige o MESMO
resultado, para a versão do navegador não se afastar da versão do servidor.

Rodar (da raiz do projeto):  .venv\\Scripts\\python -I tests\\gerar_vetores_queda.py
"""

import json
import math
import random
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from sentinela_api.sensibilidade import aplicar_sensibilidade  # noqa: E402
from sentinela_pose.config import ConfigPose, ConfigQueda  # noqa: E402
from sentinela_pose.fall_detector import DetectorQueda  # noqa: E402
from sentinela_pose.pontos import Pose  # noqa: E402

L, A = 640, 480
FPS = 10


def pose(quadril, angulo, tronco=100.0, vis=0.95, ruido=0.0, rng=None):
    """33 pontos: só ombros/quadris importam. O ombro fica a `tronco` px do quadril, inclinado `angulo` graus."""
    pontos = [[0.0, 0.0, 0.0] for _ in range(33)]
    qx, qy = quadril
    rad = math.radians(angulo)
    ox, oy = qx + tronco * math.sin(rad), qy - tronco * math.cos(rad)
    for i, (x, y) in {11: (ox - 15, oy), 12: (ox + 15, oy), 23: (qx - 12, qy), 24: (qx + 12, qy)}.items():
        if rng and ruido:
            x += rng.uniform(-ruido, ruido)
            y += rng.uniform(-ruido, ruido)
        pontos[i] = [round(x, 3), round(y, 3), vis]
    return pontos


def cena_queda(rng):
    """Em pé 2 s, cai em 0,5 s, fica deitada 6 s."""
    quadros = []
    for k in range(int(9 * FPS)):
        t = k / FPS
        if t < 2:
            q, a = (320, 250), 3
        elif t < 2.5:
            f = (t - 2) / 0.5
            q, a = (320 + 60 * f, 250 + 120 * f), 3 + 82 * f
        else:
            q, a = (380, 370), 85
        quadros.append((t, [pose(q, a, ruido=1.5, rng=rng)]))
    return quadros


def cena_queda_lenta(rng):
    """Desce aos poucos (4 s) até ficar deitada."""
    quadros = []
    for k in range(int(12 * FPS)):
        t = k / FPS
        f = min(max((t - 2) / 4, 0), 1)
        q, a = (320 + 60 * f, 250 + 120 * f), 3 + 82 * f
        quadros.append((t, [pose(q, a, ruido=1.0, rng=rng)]))
    return quadros


def cena_no_chao(rng):
    """Já entra na imagem deitada e fica 12 s (pessoa no chão, sem queda vista)."""
    return [(k / FPS, [pose((400, 380), 88, ruido=1.0, rng=rng)]) for k in range(int(14 * FPS))]


def cena_em_pe(rng):
    return [(k / FPS, [pose((320 + 3 * math.sin(k / 5), 250), 5 + 4 * math.sin(k / 7), ruido=2.0, rng=rng)]) for k in range(int(10 * FPS))]


def cena_cama(rng):
    """Deita na cama (zona de cama) e fica 15 s: não pode alertar."""
    quadros = []
    for k in range(int(18 * FPS)):
        t = k / FPS
        if t < 2:
            q, a = (300, 250), 4
        elif t < 3:
            f = t - 2
            q, a = (300 + 20 * f, 250 + 60 * f), 4 + 82 * f
        else:
            q, a = (320, 310), 86
        quadros.append((t, [pose(q, a, ruido=1.0, rng=rng)]))
    return quadros


def cena_perde_pessoa(rng):
    """Cai e o modelo perde a pessoa por 5 s; depois volta deitada."""
    quadros = []
    for k in range(int(14 * FPS)):
        t = k / FPS
        if t < 2:
            p = [pose((320, 250), 3, ruido=1.0, rng=rng)]
        elif t < 2.4:
            f = (t - 2) / 0.4
            p = [pose((320 + 60 * f, 250 + 120 * f), 3 + 82 * f, ruido=1.0, rng=rng)]
        elif t < 7:
            p = []
        else:
            p = [pose((380, 370), 85, ruido=1.0, rng=rng)]
        quadros.append((t, p))
    return quadros


def cena_duas_pessoas(rng):
    """Uma anda em pé; a outra cai e fica deitada."""
    quadros = []
    for k in range(int(10 * FPS)):
        t = k / FPS
        em_pe = pose((120 + 10 * math.sin(t), 260), 4, ruido=1.0, rng=rng)
        if t < 2:
            outra = pose((480, 250), 3, ruido=1.0, rng=rng)
        elif t < 2.5:
            f = (t - 2) / 0.5
            outra = pose((480 + 50 * f, 250 + 120 * f), 3 + 82 * f, ruido=1.0, rng=rng)
        else:
            outra = pose((530, 370), 85, ruido=1.0, rng=rng)
        quadros.append((t, [em_pe, outra]))
    return quadros


def cena_invalidas(rng):
    """Pose cortada (quadril fora da imagem), visibilidade baixa e tronco minúsculo: nada de alerta."""
    quadros = []
    for k in range(int(8 * FPS)):
        t = k / FPS
        quadros.append((t, [pose((320, 520), 85), pose((200, 200), 85, vis=0.3), pose((100, 100), 85, tronco=10)]))
    return quadros


def cena_sai_de_cena(rng):
    """Inclina-se (parece cair) perto da borda esquerda e some da imagem: não pode alertar."""
    quadros = []
    for k in range(int(10 * FPS)):
        t = k / FPS
        if t < 2:
            p = [pose((200 - 60 * t / 2, 250), 3, ruido=1.0, rng=rng)]
        elif t < 2.6:
            f = (t - 2) / 0.6
            p = [pose((60 - 30 * f, 250 + 100 * f), 3 + 82 * f, ruido=1.0, rng=rng)]
        elif t < 3.2:
            p = [pose((30, 350), 85, ruido=1.0, rng=rng)]
        else:
            p = []
        quadros.append((t, p))
    return quadros


def cena_sensibilidade(rng):
    """Inclinação de ~55°: só alerta com sensibilidade alta."""
    return [(k / FPS, [pose((350, 330), 55, ruido=1.0, rng=rng)]) for k in range(int(16 * FPS))]


CENAS = [
    ("queda", cena_queda, 0.65, None),
    ("queda_lenta", cena_queda_lenta, 0.65, None),
    ("no_chao", cena_no_chao, 0.65, None),
    ("em_pe", cena_em_pe, 0.65, None),
    ("cama", cena_cama, 0.65, [[[0.3, 0.45], [0.75, 0.45], [0.75, 0.85], [0.3, 0.85]]]),
    ("perde_pessoa", cena_perde_pessoa, 0.65, None),
    ("duas_pessoas", cena_duas_pessoas, 0.65, None),
    ("invalidas", cena_invalidas, 0.65, None),
    ("sai_de_cena", cena_sai_de_cena, 0.65, None),
    ("sensibilidade_baixa", cena_sensibilidade, 0.1, None),
    ("sensibilidade_alta", cena_sensibilidade, 0.95, None),
]


def main():
    saida = []
    for nome, fabrica, sens, cama in CENAS:
        rng = random.Random(f"sentinela-{nome}")
        cfg = aplicar_sensibilidade(ConfigQueda(), sens)
        detector = DetectorQueda(L, A, cfg, ConfigPose())
        detector.definir_zonas_cama(cama)
        quadros = []
        for t, poses in fabrica(rng):
            pessoas, alertas = detector.processar([Pose(__import__("numpy").array(p)) for p in poses], t)
            quadros.append({
                "t": t,
                "poses": poses,
                "pessoas": [{"id": p.id_pessoa, "estado": p.estado.value, "angulo": p.angulo_tronco,
                             "velocidade": p.velocidade, "temPose": p.pose is not None} for p in pessoas],
                "alertas": [{"id": a.id_pessoa, "tipo": a.tipo, "timestamp": a.timestamp, "angulo": a.angulo_tronco} for a in alertas],
            })
        saida.append({"nome": nome, "sensibilidade": sens, "cama": cama, "largura": L, "altura": A, "quadros": quadros})
        total = sum(len(q["alertas"]) for q in quadros)
        print(f"{nome}: {len(quadros)} quadros, {total} alerta(s)")

    destino = RAIZ / "web" / "tests" / "vetores_queda.json"
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(json.dumps(saida, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"gravado {destino} ({destino.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
