-- Gestão de Chamados CRN — índices e views de gestão
-- Pode ser aplicado no SQLite local: sqlite3 banco_chamados.db < schema_indices.sql
-- O app também cria os índices em _ensure_schema.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE INDEX IF NOT EXISTS idx_chamados_status ON chamados(status);
CREATE INDEX IF NOT EXISTS idx_chamados_setor ON chamados(setor);
CREATE INDEX IF NOT EXISTS idx_chamados_equipamento ON chamados(equipamento);
CREATE INDEX IF NOT EXISTS idx_chamados_abertura ON chamados(data_hora_abertura);
CREATE INDEX IF NOT EXISTS idx_chamados_conclusao ON chamados(data_hora_conclusao);
CREATE INDEX IF NOT EXISTS idx_chamados_executante ON chamados(executante);
CREATE INDEX IF NOT EXISTS idx_chamados_prioridade ON chamados(prioridade);

CREATE INDEX IF NOT EXISTS idx_equip_setor ON equipamentos(setor);
CREATE INDEX IF NOT EXISTS idx_equip_prox ON equipamentos(proxima_preventiva);
CREATE INDEX IF NOT EXISTS idx_equip_nome ON equipamentos(nome);

CREATE INDEX IF NOT EXISTS idx_manut_equip ON manutencoes_historico(equipamento_id);
CREATE INDEX IF NOT EXISTS idx_manut_data ON manutencoes_historico(data_manutencao);
CREATE INDEX IF NOT EXISTS idx_manut_tipo ON manutencoes_historico(tipo);
CREATE INDEX IF NOT EXISTS idx_manut_chamado ON manutencoes_historico(chamado_id);

CREATE INDEX IF NOT EXISTS idx_compras_status ON compras_pecas(status);
CREATE INDEX IF NOT EXISTS idx_compras_chamado ON compras_pecas(chamado_id);
CREATE INDEX IF NOT EXISTS idx_compras_data ON compras_pecas(data_solicitacao);

CREATE INDEX IF NOT EXISTS idx_almox_nome ON almox_itens(nome);
CREATE INDEX IF NOT EXISTS idx_almox_codigo ON almox_itens(codigo);
CREATE INDEX IF NOT EXISTS idx_almox_setor ON almox_itens(setor);
CREATE INDEX IF NOT EXISTS idx_mov_item ON almox_movimentacoes(item_id);
CREATE INDEX IF NOT EXISTS idx_mov_data ON almox_movimentacoes(data);

-- Views de indicadores (somente leitura)
CREATE VIEW IF NOT EXISTS vw_backlog AS
SELECT
    id, setor, equipamento, prioridade, status, executante,
    solicitante, data_hora_abertura,
    ROUND((julianday('now') - julianday(data_hora_abertura)) * 24, 1) AS idade_horas
FROM chamados
WHERE status IN ('Aberto', 'Em Atendimento', 'Aguardando Peça');

CREATE VIEW IF NOT EXISTS vw_mttr AS
SELECT
    id, setor, equipamento, executante, prioridade,
    data_hora_inicio, data_hora_conclusao,
    ROUND((julianday(data_hora_conclusao) - julianday(data_hora_inicio)) * 24, 2) AS mttr_horas
FROM chamados
WHERE status = 'Concluído'
  AND data_hora_inicio IS NOT NULL
  AND data_hora_conclusao IS NOT NULL;

CREATE VIEW IF NOT EXISTS vw_reincidencia AS
SELECT equipamento, COUNT(*) AS qtd
FROM chamados
WHERE equipamento IS NOT NULL AND TRIM(equipamento) <> ''
GROUP BY equipamento
HAVING COUNT(*) >= 2
ORDER BY qtd DESC;

CREATE VIEW IF NOT EXISTS vw_preventivas_vencidas AS
SELECT
    id, nome, setor, marca, modelo, numero_patrimonio,
    ultima_preventiva, proxima_preventiva
FROM equipamentos
WHERE proxima_preventiva IS NOT NULL
  AND date(proxima_preventiva) <= date('now')
  AND (silenciar_ate IS NULL OR date(silenciar_ate) < date('now'));

CREATE VIEW IF NOT EXISTS vw_estoque_critico AS
SELECT id, codigo, nome, categoria, quantidade, estoque_min, localizacao, setor
FROM almox_itens
WHERE COALESCE(ativo, 1) = 1
  AND COALESCE(quantidade, 0) <= COALESCE(estoque_min, 0);
