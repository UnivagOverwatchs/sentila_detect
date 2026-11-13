#!/usr/bin/env bash
# backup.sh - Cópia diária do Sentinela na VPS: banco (pg_dump) + fotos dos alertas.
#
# LÓGICA
#   1. pg_dump dentro do container do Postgres (formato custom, comprimido) -> banco-AAAA-MM-DD.dump
#   2. tar.gz da pasta de fotos montada no painel                       -> fotos-AAAA-MM-DD.tar.gz
#   3. apaga cópias com mais de MANTER_DIAS dias (padrão 14)
# Os arquivos ficam em /opt/sentinela/backups com permissão só do root (têm dados de residentes: LGPD).
# Importante: copie essa pasta para FORA da VPS de vez em quando (se a VPS sumir, o backup some junto).
#
# Uso:    bash /opt/sentinela/deploy/backup.sh
# Cron:   15 3 * * * bash /opt/sentinela/deploy/backup.sh >> /var/log/sentinela-backup.log 2>&1
# Restaurar o banco:
#   docker exec -i sentinela pg_restore -U sentinelas -d sentinela --clean --if-exists < banco-AAAA-MM-DD.dump

set -euo pipefail

CONTAINER_PG="${CONTAINER_PG:-sentinela}"          # nome do container do PostgreSQL
PGUSUARIO="${PGUSUARIO:-sentinelas}"
PGBANCO="${PGBANCO:-sentinela}"
PASTA_FOTOS="${PASTA_FOTOS:-/opt/sentinela/dados/alertas}"
DESTINO="${DESTINO:-/opt/sentinela/backups}"
MANTER_DIAS="${MANTER_DIAS:-14}"

umask 077                                          # arquivos legíveis só pelo root
mkdir -p "$DESTINO"
dia="$(date +%F)"

# 1) banco: escreve num .parcial e só renomeia se terminou bem (nunca fica um backup pela metade com nome válido)
docker exec "$CONTAINER_PG" pg_dump -U "$PGUSUARIO" -d "$PGBANCO" -Fc > "$DESTINO/banco-$dia.dump.parcial"
mv "$DESTINO/banco-$dia.dump.parcial" "$DESTINO/banco-$dia.dump"

# 2) fotos
if [ -d "$PASTA_FOTOS" ]; then
  tar -czf "$DESTINO/fotos-$dia.tar.gz.parcial" -C "$PASTA_FOTOS" .
  mv "$DESTINO/fotos-$dia.tar.gz.parcial" "$DESTINO/fotos-$dia.tar.gz"
fi

# 3) rotação
find "$DESTINO" -maxdepth 1 -type f \( -name 'banco-*.dump' -o -name 'fotos-*.tar.gz' -o -name '*.parcial' \) \
  -mtime +"$MANTER_DIAS" -delete

echo "$(date '+%F %T') backup ok: $(du -sh "$DESTINO" | cut -f1) em $DESTINO"
