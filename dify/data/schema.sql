-- 《记仇小镇：NPC 的复仇日记》seekdb (OceanBase) 数据库 Schema
--
-- 目标库：memory_town（可在 .env 中用 TOWN_SEEKDB_DATABASE 覆盖）
-- 字符集：utf8mb4 / utf8mb4_bin
--
-- 建库由 backend/town_backend/store.py 的 initialize() 负责，
-- 因此这里不含 CREATE DATABASE / USE，所有语句都作用于当前连接选中的库。
--
-- 设计要点：
--   1. 每个玩家的记忆、关系、道具、事件都按 player_id 隔离，索引以 player_id 打头，
--      因此"按玩家查询"永远是索引前缀扫描，不会扫到别人的行。
--   2. 事件表带 idempotency_key 唯一键，重复提交同一动作只会命中同一条记录，
--      由应用层判定为"重复"而不是"再执行一次"。
--   3. 道具归属与关系数值都有 CHECK 约束，非法状态在数据库层就被拒绝。

-- ---------------------------------------------------------------- 地点
CREATE TABLE IF NOT EXISTS `town_location` (
  location_id    VARCHAR(64)  NOT NULL,
  name           VARCHAR(128) NOT NULL,
  description    VARCHAR(1024) NOT NULL,
  is_start       TINYINT(1)   NOT NULL DEFAULT 0,
  created_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`location_id`),
  KEY `ix_location_start` (`is_start`)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ---------------------------------------------------------------- NPC
CREATE TABLE IF NOT EXISTS `town_npc` (
  npc_id         VARCHAR(64)  NOT NULL,
  name           VARCHAR(128) NOT NULL,
  title          VARCHAR(128) NOT NULL,
  persona        VARCHAR(2048) NOT NULL,
  speech_style   VARCHAR(512) NOT NULL,
  home_location  VARCHAR(64)  NOT NULL,
  grudge_focus   VARCHAR(512) NOT NULL,
  created_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`npc_id`),
  KEY `ix_npc_home` (`home_location`)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ---------------------------------------------------------------- 玩家
CREATE TABLE IF NOT EXISTS `town_player` (
  player_id      VARCHAR(128) NOT NULL,
  display_name   VARCHAR(128) NOT NULL,
  current_location VARCHAR(64) NOT NULL,
  session_id     VARCHAR(128) NOT NULL,
  turn_count     INT          NOT NULL DEFAULT 0,
  created_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`player_id`),
  KEY `ix_player_session` (`session_id`)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ---------------------------------------------------------------- 关系状态
-- affinity: -100 (死敌) .. 100 (挚友)
-- trust:    0 (完全不信) .. 100 (完全信任)
CREATE TABLE IF NOT EXISTS `town_relationship` (
  player_id      VARCHAR(128) NOT NULL,
  npc_id         VARCHAR(64)  NOT NULL,
  affinity       INT          NOT NULL DEFAULT 0,
  trust          INT          NOT NULL DEFAULT 0,
  grudge_level   INT          NOT NULL DEFAULT 0,
  last_action    VARCHAR(64)  NOT NULL DEFAULT '',
  updated_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`player_id`, `npc_id`),
  KEY `ix_rel_player` (`player_id`),
  CONSTRAINT `ck_rel_affinity` CHECK (`affinity` BETWEEN -100 AND 100),
  CONSTRAINT `ck_rel_trust`    CHECK (`trust`    BETWEEN 0   AND 100),
  CONSTRAINT `ck_rel_grudge`   CHECK (`grudge_level` BETWEEN 0 AND 100)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ---------------------------------------------------------------- 道具
-- 道具是"实例 + 持有者"的组合：主键是 (item_id, owner_kind, owner_id)。
-- 同一件道具可以同时存在于镇上的货架（town）与某个 NPC 手里（npc），
-- 因此把小鱼干送出去之后，镇上仍然还有货可以送（quantity 减 1 而非清零）。
-- owner_kind: npc / player / town
CREATE TABLE IF NOT EXISTS `town_item` (
  item_id        VARCHAR(64)  NOT NULL,
  owner_kind     VARCHAR(32)  NOT NULL,
  owner_id       VARCHAR(128) NOT NULL,
  name           VARCHAR(128) NOT NULL,
  description    VARCHAR(512) NOT NULL,
  quantity       INT          NOT NULL DEFAULT 1,
  is_transferable TINYINT(1)  NOT NULL DEFAULT 1,
  created_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`item_id`, `owner_kind`, `owner_id`),
  KEY `ix_item_owner` (`owner_kind`, `owner_id`),
  KEY `ix_item_id` (`item_id`),
  CONSTRAINT `ck_item_owner_kind` CHECK (`owner_kind` IN ('npc', 'player', 'town')),
  CONSTRAINT `ck_item_quantity` CHECK (`quantity` >= 1)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ---------------------------------------------------------------- 游戏事件
-- idempotency_key 保证"同一个动作请求重复提交"不会产生第二条事件。
CREATE TABLE IF NOT EXISTS `town_event` (
  event_id       VARCHAR(64)  NOT NULL,
  player_id      VARCHAR(128) NOT NULL,
  npc_id         VARCHAR(64)  NOT NULL,
  action_type    VARCHAR(32)  NOT NULL,
  action_text    VARCHAR(1024) NOT NULL,
  item_id        VARCHAR(64)  NOT NULL DEFAULT '',
  outcome        VARCHAR(1024) NOT NULL,
  affinity_delta INT          NOT NULL DEFAULT 0,
  trust_delta    INT          NOT NULL DEFAULT 0,
  grudge_delta   INT          NOT NULL DEFAULT 0,
  session_id     VARCHAR(128) NOT NULL,
  idempotency_key VARCHAR(190) NOT NULL,
  created_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`event_id`),
  UNIQUE KEY `ux_event_idempotency` (`idempotency_key`),
  KEY `ix_event_player` (`player_id`, `created_at`),
  KEY `ix_event_npc` (`player_id`, `npc_id`),
  CONSTRAINT `ck_event_action` CHECK (
    `action_type` IN ('talk', 'prank', 'gift', 'steal', 'investigate', 'unknown')
  )
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ---------------------------------------------------------------- 剧情进度
-- 每个玩家在每个剧情节点上的状态。
CREATE TABLE IF NOT EXISTS `town_plot_progress` (
  player_id      VARCHAR(128) NOT NULL,
  plot_id        VARCHAR(64)  NOT NULL,
  stage          VARCHAR(64)  NOT NULL,
  triggered      TINYINT(1)   NOT NULL DEFAULT 0,
  detail         VARCHAR(1024) NOT NULL DEFAULT '',
  updated_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`player_id`, `plot_id`),
  KEY `ix_plot_player` (`player_id`)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ---------------------------------------------------------------- 幂等记录
-- 记录"一次请求"的最终结果，用于把重复请求映射回同一次结果。
CREATE TABLE IF NOT EXISTS `town_request_log` (
  idempotency_key VARCHAR(190) NOT NULL,
  player_id      VARCHAR(128) NOT NULL,
  request_hash   CHAR(64)    NOT NULL,
  response_json  LONGTEXT    NOT NULL,
  created_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`idempotency_key`),
  KEY `ix_reqlog_player` (`player_id`)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
