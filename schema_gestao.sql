-- ============================================================
-- Gestão de Chamados CRN — schema de gestão (idempotente)
-- SQLite local e SQLite Cloud.
-- Aplicar: sqlite3 banco_chamados.db < schema_gestao.sql
-- O app também cria tabelas/índices em database._ensure_schema.
-- ============================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ---- Índices de tela e relatório --------------------------------
CREATE INDEX IF NOT EXISTS idx_chamados_status ON chamados(status);
CREATE INDEX IF NOT EXISTS idx_chamados_setor ON chamados(setor);
CREATE INDEX IF NOT EXISTS idx_chamados_equipamento ON chamados(equipamento);
CREATE INDEX IF NOT EXISTS idx_chamados_abertura ON chamados(data_hora_abertura);
CREATE INDEX IF NOT EXISTS idx_chamados_inicio ON chamados(data_hora_inicio);
CREATE INDEX IF NOT EXISTS idx_chamados_conclusao ON chamados(data_hora_conclusao);
CREATE INDEX IF NOT EXISTS idx_chamados_executante ON chamados(executante);
CREATE INDEX IF NOT EXISTS idx_chamados_prioridade ON chamados(prioridade);
CREATE INDEX IF NOT EXISTS idx_chamados_status_abertura ON chamados(status, data_hora_abertura);
CREATE INDEX IF NOT EXISTS idx_chamados_exec_status ON chamados(executante, status);

CREATE INDEX IF NOT EXISTS idx_equip_setor ON equipamentos(setor);
CREATE INDEX IF NOT EXISTS idx_equip_nome ON equipamentos(nome);
CREATE INDEX IF NOT EXISTS idx_equip_prox ON equipamentos(proxima_preventiva);
CREATE INDEX IF NOT EXISTS idx_equip_patrimonio ON equipamentos(numero_patrimonio);

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

-- Histórico operacional (abertura, início, peça, conclusão, WhatsApp)
CREATE TABLE IF NOT EXISTS chamado_eventos (
    id INTEGER PRIMARY KEY,
    chamado_id INTEGER NOT NULL,
    data_hora TEXT,
    tipo TEXT,
    usuario TEXT,
    detalhe TEXT
);
CREATE INDEX IF NOT EXISTS idx_eventos_chamado ON chamado_eventos(chamado_id, data_hora);

-- Fotos locais + link remoto (Drive)
CREATE TABLE IF NOT EXISTS chamado_fotos (
    id INTEGER PRIMARY KEY,
    chamado_id INTEGER,
    tipo TEXT,
    path_local TEXT,
    url_remota TEXT,
    destino TEXT,
    data_envio TEXT
);
CREATE INDEX IF NOT EXISTS idx_fotos_chamado ON chamado_fotos(chamado_id);

CREATE TABLE IF NOT EXISTS integracoes_log (
    id INTEGER PRIMARY KEY,
    data_hora TEXT,
    canal TEXT,
    destino TEXT,
    chamado_id INTEGER,
    ok INTEGER,
    detalhe TEXT
);
CREATE INDEX IF NOT EXISTS idx_integracoes_data ON integracoes_log(data_hora);
CREATE INDEX IF NOT EXISTS idx_integracoes_canal ON integracoes_log(canal);
CREATE INDEX IF NOT EXISTS idx_integracoes_chamado ON integracoes_log(chamado_id);

-- ---- Views de decisão diária ------------------------------------
DROP VIEW IF EXISTS vw_backlog;
CREATE VIEW vw_backlog AS
SELECT
    id, setor, equipamento, prioridade, status, executante,
    solicitante, data_hora_abertura,
    ROUND((julianday('now') - julianday(data_hora_abertura)) * 24, 1) AS idade_horas
FROM chamados
WHERE status IN ('Aberto', 'Em Atendimento', 'Aguardando Peça');

DROP VIEW IF EXISTS vw_mttr;
CREATE VIEW vw_mttr AS
SELECT
    id, setor, equipamento, executante, prioridade,
    data_hora_inicio, data_hora_conclusao,
    ROUND((julianday(data_hora_conclusao) - julianday(data_hora_inicio)) * 24, 2) AS mttr_horas,
    ROUND((julianday(data_hora_conclusao) - julianday(data_hora_abertura)) * 24, 2) AS ciclo_horas
FROM chamados
WHERE status = 'Concluído'
  AND data_hora_conclusao IS NOT NULL;

DROP VIEW IF EXISTS vw_tempo_resposta;
CREATE VIEW vw_tempo_resposta AS
SELECT
    id, setor, equipamento, prioridade, executante,
    data_hora_abertura, data_hora_inicio,
    ROUND((julianday(data_hora_inicio) - julianday(data_hora_abertura)) * 24, 2) AS resposta_horas
FROM chamados
WHERE data_hora_abertura IS NOT NULL
  AND data_hora_inicio IS NOT NULL;

DROP VIEW IF EXISTS vw_aguardando_peca;
CREATE VIEW vw_aguardando_peca AS
SELECT
    id, setor, equipamento, prioridade, executante,
    peca_solicitada, data_solicitacao_peca, data_hora_abertura,
    ROUND((julianday('now') - julianday(COALESCE(data_solicitacao_peca, data_hora_abertura))) * 24, 1) AS horas_parada
FROM chamados
WHERE status = 'Aguardando Peça';

DROP VIEW IF EXISTS vw_carga_tecnico;
CREATE VIEW vw_carga_tecnico AS
SELECT
    COALESCE(NULLIF(TRIM(executante), ''), '(sem técnico)') AS tecnico,
    SUM(CASE WHEN status = 'Aberto' THEN 1 ELSE 0 END) AS abertos,
    SUM(CASE WHEN status = 'Em Atendimento' THEN 1 ELSE 0 END) AS em_atendimento,
    SUM(CASE WHEN status = 'Aguardando Peça' THEN 1 ELSE 0 END) AS aguardando_peca,
    COUNT(*) AS wip
FROM chamados
WHERE status IN ('Aberto', 'Em Atendimento', 'Aguardando Peça')
GROUP BY COALESCE(NULLIF(TRIM(executante), ''), '(sem técnico)');

DROP VIEW IF EXISTS vw_reincidencia;
CREATE VIEW vw_reincidencia AS
SELECT equipamento, COUNT(*) AS qtd
FROM chamados
WHERE equipamento IS NOT NULL AND TRIM(equipamento) <> ''
GROUP BY equipamento
HAVING COUNT(*) >= 2;

DROP VIEW IF EXISTS vw_preventivas_vencidas;
CREATE VIEW vw_preventivas_vencidas AS
SELECT
    id, nome, setor, marca, modelo, numero_patrimonio,
    ultima_preventiva, proxima_preventiva,
    CAST(julianday('now') - julianday(proxima_preventiva) AS INTEGER) AS dias_atraso
FROM equipamentos
WHERE proxima_preventiva IS NOT NULL
  AND date(proxima_preventiva) <= date('now')
  AND (silenciar_ate IS NULL OR date(silenciar_ate) < date('now'));

DROP VIEW IF EXISTS vw_estoque_critico;
CREATE VIEW vw_estoque_critico AS
SELECT id, codigo, nome, categoria, quantidade, estoque_min, localizacao, setor
FROM almox_itens
WHERE COALESCE(ativo, 1) = 1
  AND COALESCE(quantidade, 0) <= COALESCE(estoque_min, 0);
