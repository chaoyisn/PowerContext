-- 《记仇小镇》V2 数据库迁移
--
-- 目标库：memory_town（与 V1 同一个库，**不重建、不删除**）
--
-- 迁移策略：**增量**。
--   1. V1 的 8 张表全部保留，已有行一列不动。
--   2. ALTER TABLE ... ADD COLUMN 由迁移脚本执行，脚本会先查 information_schema，
--      列已存在就跳过 —— 因此本文件可以反复执行。
--   3. CHECK 约束需要放宽时先 DROP 再 ADD。
--   4. 新表用 CREATE TABLE IF NOT EXISTS。
--
-- V1 → V2 的数据变化：
--   * town_npc 增加 1 个 NPC（乌鸦法官 crow_judge）
--   * town_location 增加到 4 个地点，并新增 town_location_link 连接表
--   * town_player 增加金币、任务、结局字段
--   * town_item 增加线索类道具标记
--   * town_event 支持 V2 的动作类型与"是否真的执行"
--   * 新增 town_knowledge（知情传播）、town_quest（任务）、town_ending（结局）、
--     town_achievement（成就）、town_outbox（记忆补偿队列）

-- ---------------------------------------------------------------- 地点（V1 表，仅补齐 V2 需要的列）
ALTER TABLE `town_location` ADD COLUMN `is_reachable` TINYINT(1) NOT NULL DEFAULT 1;

-- ---------------------------------------------------------------- NPC（V1 表，增量列）
-- NPC 之间的社会关系：墨墨与镇长是否结盟、乌鸦法官的辖区。
ALTER TABLE `town_npc` ADD COLUMN `faction` VARCHAR(32) NOT NULL DEFAULT 'town';
ALTER TABLE `town_npc` ADD COLUMN `ally_npc_id` VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE `town_npc` ADD COLUMN `knowledge_tags` VARCHAR(512) NOT NULL DEFAULT '';

-- ---------------------------------------------------------------- 玩家（V1 表，增量列）
ALTER TABLE `town_player` ADD COLUMN `coins` INT NOT NULL DEFAULT 20;
ALTER TABLE `town_player` ADD COLUMN `current_quest` VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE `town_player` ADD COLUMN `ending_id` VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE `town_player` ADD COLUMN `ending_claimed` TINYINT(1) NOT NULL DEFAULT 0;

-- ---------------------------------------------------------------- 道具（V1 表，增量列）
-- V2 有"线索"这类只能拾取、不能赠送的道具。
ALTER TABLE `town_item` ADD COLUMN `item_kind` VARCHAR(32) NOT NULL DEFAULT 'normal';
ALTER TABLE `town_item` ADD COLUMN `is_evidence` TINYINT(1) NOT NULL DEFAULT 0;

-- ---------------------------------------------------------------- 事件（V1 表，增量列）
-- 事件还要记录"这是不是一次真实的、已执行的动作"，用于跨会话推理。
ALTER TABLE `town_event` ADD COLUMN `is_committed` TINYINT(1) NOT NULL DEFAULT 1;
ALTER TABLE `town_event` ADD COLUMN `location_id` VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE `town_event` ADD COLUMN `confidence` INT NOT NULL DEFAULT 0;

-- V2 的动作类型比 V1 多，CHECK 约束必须放宽，否则合法动作会被数据库拒绝。
ALTER TABLE `town_event` DROP CHECK `ck_event_action`;
ALTER TABLE `town_event` ADD CONSTRAINT `ck_event_action` CHECK (
    `action_type` IN (
      'talk', 'prank', 'gift', 'steal', 'investigate', 'unknown',
      'return_item', 'apologize', 'move', 'help', 'bribe'
    )
  );

-- ---------------------------------------------------------------- 剧情进度（V1 表，增量列）
ALTER TABLE `town_plot_progress` ADD COLUMN `stage_flags` VARCHAR(255) NOT NULL DEFAULT '';
ALTER TABLE `town_plot_progress` ADD COLUMN `ending_id` VARCHAR(64) NOT NULL DEFAULT '';

-- ---------------------------------------------------------------- 玩家身份
-- （上面 CREATE TABLE IF NOT EXISTS 会建出完整结构；下面这句负责给
--   **已经存在**的旧表补列，迁移脚本会先查 information_schema 再决定
--   跳过还是执行，因此整个文件可以反复执行。）
ALTER TABLE `town_player_identity` ADD COLUMN `secret_hash` VARCHAR(128) NOT NULL DEFAULT '';

-- 把 player_id 绑定到两样东西上：
--
--   * owner_identity —— **身份**。来自 {{#sys.user_id#}}：
--     Service API 上是已认证的终端用户，Console 调试时是控制台账号。
--   * secret_hash   —— **密令**。玩家自己输入的口令。
--
-- 为什么两个都要：Console 调试模式下所有测试者共享同一个控制台身份，
-- 只靠身份并不能阻止一个人冒用另一个人的存档。密令才是"这把钥匙归我"
-- 的那一半。两者都要对，才准读这个存档。
--
-- 规则是"一个玩家只属于一个身份"，而不是反过来：
--   * 同一个 player_id 换身份访问 → 拒绝；
--   * 同一个身份可以拥有多个 player_id（同一真人开多个存档）；
--   * 密令一旦设定就不能被另一个密令顶替（顶替意味着接管存档）。
--
-- 因此光知道 player_id 不足以读到别人的状态。
-- token_hash / secret_hash 只存哈希：明文仅在签发/设定时返回一次。
CREATE TABLE IF NOT EXISTS `town_player_identity` (
  player_id      VARCHAR(128) NOT NULL,
  owner_identity VARCHAR(128) NOT NULL DEFAULT '',
  secret_hash    VARCHAR(128) NOT NULL DEFAULT '',
  token_hash     VARCHAR(128) NOT NULL DEFAULT '',
  created_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`player_id`),
  KEY `ix_identity_owner` (`owner_identity`),
  KEY `ix_identity_player` (`player_id`)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ---------------------------------------------------------------- 地点连接
-- V2 的 move 动作靠这张表校验"能不能走过去"，而不是随便传一个 location_id。
CREATE TABLE IF NOT EXISTS `town_location_link` (
  from_location VARCHAR(64) NOT NULL,
  to_location   VARCHAR(64) NOT NULL,
  travel_cost   INT         NOT NULL DEFAULT 0,
  PRIMARY KEY (`from_location`, `to_location`),
  CONSTRAINT `ck_link_cost` CHECK (`travel_cost` >= 0)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ---------------------------------------------------------------- 知情传播
-- NPC 不能凭空知道秘密。每一个"谁知道什么事"都必须落库：
--   玩家知道自己做的每一件事；
--   某个 NPC 只有在明确"被告知"或"当场目击"之后才会知道。
-- NPC 台词里只会引用 knowledge 里有的事件。
CREATE TABLE IF NOT EXISTS `town_knowledge` (
  knowledge_id   VARCHAR(64)  NOT NULL,
  player_id      VARCHAR(128) NOT NULL,
  subject_kind   VARCHAR(32)  NOT NULL,
  subject_id     VARCHAR(64)  NOT NULL,
  topic          VARCHAR(64)  NOT NULL,
  detail         VARCHAR(512) NOT NULL DEFAULT '',
  learned_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`knowledge_id`),
  UNIQUE KEY `ux_knowledge` (`player_id`, `subject_kind`, `subject_id`, `topic`),
  KEY `ix_knowledge_player` (`player_id`),
  KEY `ix_knowledge_subject` (`player_id`, `subject_kind`, `subject_id`)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ---------------------------------------------------------------- 任务
-- 任务与进度都存权威数值，结局判定只看这些数字，不看模型说了什么。
CREATE TABLE IF NOT EXISTS `town_quest` (
  player_id      VARCHAR(128) NOT NULL,
  quest_id       VARCHAR(64)  NOT NULL,
  title          VARCHAR(128) NOT NULL,
  stage          VARCHAR(64)  NOT NULL DEFAULT '',
  progress       INT         NOT NULL DEFAULT 0,
  required       INT         NOT NULL DEFAULT 1,
  state          VARCHAR(32)  NOT NULL DEFAULT 'active',
  detail         VARCHAR(512) NOT NULL DEFAULT '',
  updated_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`player_id`, `quest_id`),
  KEY `ix_quest_player` (`player_id`),
  CONSTRAINT `ck_quest_progress` CHECK (`progress` >= 0),
  CONSTRAINT `ck_quest_state` CHECK (`state` IN ('active', 'done', 'failed'))
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ---------------------------------------------------------------- 结局
-- 结局是"玩家 + 结局"的唯一行。同一结局只能领取一次奖励。
CREATE TABLE IF NOT EXISTS `town_ending` (
  player_id      VARCHAR(128) NOT NULL,
  ending_id      VARCHAR(64)  NOT NULL,
  ending_kind    VARCHAR(64)  NOT NULL,
  title          VARCHAR(128) NOT NULL,
  summary        VARCHAR(512) NOT NULL DEFAULT '',
  reward_coins   INT          NOT NULL DEFAULT 0,
  reward_claimed TINYINT(1)   NOT NULL DEFAULT 0,
  reached_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`player_id`, `ending_id`),
  KEY `ix_ending_player` (`player_id`),
  CONSTRAINT `ck_ending_reward` CHECK (`reward_claimed` IN (0, 1))
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ---------------------------------------------------------------- 成就
CREATE TABLE IF NOT EXISTS `town_achievement` (
  player_id      VARCHAR(128) NOT NULL,
  achievement_id VARCHAR(64)  NOT NULL,
  title          VARCHAR(128) NOT NULL,
  detail         VARCHAR(512) NOT NULL DEFAULT '',
  unlocked_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`player_id`, `achievement_id`)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ---------------------------------------------------------------- Outbox
-- 跨系统写入一致性：seekdb 事务里把"该写进 PowerContext 的关键事件"
-- 一起提交到 outbox。PowerContext 写成功后标记 done；写失败则留 pending，
-- 由补偿流程重试。这样 seekdb 已提交、记忆未写 的中间状态是可恢复的，
-- 而不是被悄悄吞掉。
-- dedupe_key 保证重试不会产生重复记忆。
CREATE TABLE IF NOT EXISTS `town_outbox` (
  outbox_id      VARCHAR(64)  NOT NULL,
  player_id      VARCHAR(128) NOT NULL,
  dedupe_key     VARCHAR(190) NOT NULL,
  kind           VARCHAR(64)  NOT NULL,
  payload        VARCHAR(2048) NOT NULL,
  state          VARCHAR(16)  NOT NULL DEFAULT 'pending',
  attempts       INT          NOT NULL DEFAULT 0,
  last_error     VARCHAR(512) NOT NULL DEFAULT '',
  created_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`outbox_id`),
  UNIQUE KEY `ux_outbox_dedupe` (`dedupe_key`),
  KEY `ix_outbox_state` (`state`, `created_at`),
  CONSTRAINT `ck_outbox_state` CHECK (`state` IN ('pending', 'done', 'failed'))
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
