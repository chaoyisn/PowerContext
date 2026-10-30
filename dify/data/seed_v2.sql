-- 《记仇小镇》V2 种子数据（增量）
--
-- 幂等：全部使用 INSERT ... ON DUPLICATE KEY UPDATE，重复执行不产生重复行。
-- V1 的行会被更新成 V2 的内容（人设扩充、加入新 NPC），但不会删除。

-- ---------------------------------------------------------------- 地点
-- V2 的 4 个地点全部可达。镇长宅邸改名为「镇长办公室」，
-- 因为 V2 的洗白结局要求"当着镇长的面把王冠还回去"。
INSERT INTO `town_location` (`location_id`, `name`, `description`, `is_start`, `is_reachable`) VALUES
  ('town_square', '小镇广场', '镇子正中央的青石广场。告示牌上钉着镇长的三条禁令，喷泉边的长椅上总躺着那只肥猫。', 1, 1),
  ('mayor_house', '镇长办公室', '镇长办公兼起居的地方。门廊上挂着镀金的王冠形状灯罩——那不是王冠，是道具。', 0, 1),
  ('back_alley', '神秘后巷', '广场背后的窄巷。堆着空木箱，墙上写满了「再也不给猫加餐」的字样。', 0, 1),
  ('detective_office', '侦探事务所', '二楼一间由旧阁楼改造的屋子。满地都是卷宗，墨墨用墨水笔把每个嫌疑人的名字划掉了又写上。', 0, 1)
ON DUPLICATE KEY UPDATE
  `name` = VALUES(`name`),
  `description` = VALUES(`description`),
  `is_start` = VALUES(`is_start`),
  `is_reachable` = VALUES(`is_reachable`);

-- ---------------------------------------------------------------- 地点连接
-- move 动作只能沿着这张表走。神秘后巷是"只有猫知道的路"，
-- 所以它与侦探事务所互为邻居。
INSERT INTO `town_location_link` (`from_location`, `to_location`, `travel_cost`) VALUES
  ('town_square', 'mayor_house', 0),
  ('mayor_house', 'town_square', 0),
  ('town_square', 'back_alley', 0),
  ('back_alley', 'town_square', 0),
  ('back_alley', 'detective_office', 0),
  ('detective_office', 'back_alley', 0),
  ('detective_office', 'town_square', 0),
  ('town_square', 'detective_office', 0),
  ('mayor_house', 'detective_office', 0),
  ('detective_office', 'mayor_house', 0)
ON DUPLICATE KEY UPDATE `travel_cost` = VALUES(`travel_cost`);

-- ---------------------------------------------------------------- NPC
-- 三个 NPC：镇长记仇、侦探墨墨记证据、乌鸦法官记判决。
INSERT INTO `town_npc` (`npc_id`, `name`, `title`, `persona`, `speech_style`, `home_location`, `grudge_focus`, `faction`, `ally_npc_id`, `knowledge_tags`) VALUES
  ('mayor', '奥托镇长',
   '小镇镇长',
   '奥托镇长表面上是个威严、爱发号施令的老派官僚，实则极度爱惜羽毛、记仇心极强。任何在他管辖区发生的不体面事件——尤其是让他当众丢脸的——都会被他在心里逐条记账、写进日记，日后一定会找补回来。他最不能容忍的是别人看穿他的虚张声势。一旦有人偷走象征他权威的东西，他会立刻启动调查姿态，用程序正义的名义展开报复；但如果对方主动认错、归还赃物、并愿意给他一个体面的台阶，他其实比谁都吃这一套——他要的是面子，不是真的要把人送进监狱。',
   '官腔十足，喜欢用「根据镇规第X条」，句子偏长，偶尔会漏出小地方口音；越生气越礼貌；被奉承时会突然变得和蔼。',
   'town_square',
   '权威被冒犯、当众丢脸、被小看',
   'town', '', 'crown,theft,authority'),
  ('cat_detective', '墨墨',
   '猫咪侦探',
   '墨墨是一只穿着旧风衣的胖橘猫，自称本镇唯一持证侦探。它说话爱故作神秘，喜欢用推理的口吻把鸡毛蒜皮的事说得像惊天大案。它记仇的方式是记账本——它相信证据不会说谎，所以会翻旧账揭穿玩家。它表面冷淡毒舌，但对愿意给它加餐的玩家会松口；它讨厌被当宠物而不是被当同行。它绝不凭空指控——没有证据的事它一个字都不说，哪怕是它亲眼看到的传闻。它只承认两种来源：自己查到的，和别人亲口告诉它的。',
   '慢悠悠、拖长音、爱用「啊哈」和「本案」，偶尔喵一声；越生气越爱讲道理；提到证据时会突然严肃起来。',
   'town_square',
   '被当成宠物、被敷衍、线索被忽视',
   'town', '', 'clue,evidence,bribe,promise'),
  ('crow_judge', '渡鸦法官',
   '巡回法官',
   '渡鸦法官是一位穿着过分正式的黑色长袍、脖子上系着浆得笔挺白领结的渡鸦。他一本正经地审理这个小镇上所有荒诞的案件：猫的偷鱼案、雕像被涂鸦案、以及某个胆大妄为的市民从镇长头上顺走王冠案。他相信程序，但更相信**记录**：他会翻阅卷宗、核对证物、听取证词，然后做出一个往往出人意料但逻辑自洽的判决。他不记仇——他只记**案卷**。被他判决过一次的人，下一次会被翻出旧卷宗；被他判无罪的人，会拿到一张正式的免责状。',
   '字正腔圆、一板一眼、喜欢用「本庭」「证据不足」「记录在案」；偶尔会用渡鸦特有的沙哑比喻；判决时格外简短有力。',
   'detective_office',
   '证据被伪造、程序被跳过、被当众喊破身份',
   'court', '', 'trial,evidence,testimony,record')
ON DUPLICATE KEY UPDATE
  `name` = VALUES(`name`),
  `title` = VALUES(`title`),
  `persona` = VALUES(`persona`),
  `speech_style` = VALUES(`speech_style`),
  `home_location` = VALUES(`home_location`),
  `grudge_focus` = VALUES(`grudge_focus`),
  `faction` = VALUES(`faction`),
  `ally_npc_id` = VALUES(`ally_npc_id`),
  `knowledge_tags` = VALUES(`knowledge_tags`);

-- ---------------------------------------------------------------- 道具
-- 新增线索类道具：只能拾取（item_kind='clue'），不能赠送也不能偷。
-- 线索是"悬案大师"结局的关键材料。
INSERT INTO `town_item`
  (`item_id`, `owner_kind`, `owner_id`, `name`, `description`, `quantity`, `is_transferable`, `item_kind`, `is_evidence`) VALUES
  ('crown_receipt', 'town', 'back_alley', '一张王冠领用单', '后巷垃圾桶里的一张领用单，上面写着「王冠 · 领用人：奥托镇长 · 领用日期：忘了」。日期栏是空的。', 1, 1, 'clue', 1),
  ('alley_witness_note', 'town', 'detective_office', '后巷目击者便条', '有人匿名塞进门缝的纸条：「那晚后巷有动静。我什么都没看见。」字迹在发抖。', 1, 1, 'clue', 1),
  ('town_badge', 'npc', 'crow_judge', '法庭铜徽', '渡鸦法官胸前别着的铜徽，据说是这个法庭唯一认的东西。', 1, 0, 'normal', 0),
  ('fish_premium', 'town', 'town_square', '进口小鱼干', '镇上唯一一包进口小鱼干。墨墨闻到这个味道会失去原则。', 2, 1, 'normal', 0)
ON DUPLICATE KEY UPDATE
  `name` = VALUES(`name`),
  `description` = VALUES(`description`),
  `quantity` = VALUES(`quantity`),
  `is_transferable` = VALUES(`is_transferable`),
  `item_kind` = VALUES(`item_kind`),
  `is_evidence` = VALUES(`is_evidence`);

-- V1 的道具补上 V2 的列（item_kind / is_evidence 默认值已在迁移里设好，
-- 这里只补一条不需要的数据，保持文件可独立执行）。
INSERT INTO `town_item`
  (`item_id`, `owner_kind`, `owner_id`, `name`, `description`, `quantity`, `is_transferable`, `item_kind`, `is_evidence`) VALUES
  ('golden_crown', 'npc', 'mayor', '镇长的金王冠', '镇长视若珍宝的镀金王冠，底座刻着「奥托镇长万岁」。它很值钱，也很招贼。', 1, 1, 'normal', 0),
  ('fat_fish_snack', 'town', 'town_square', '油炸小鱼干', '喷泉边卖的那种小鱼干，油纸包。墨墨的弱点。', 5, 1, 'normal', 0),
  ('fat_fish_snack', 'npc', 'cat_detective', '油炸小鱼干', '墨墨私藏的油炸小鱼干，还没吃完。', 1, 1, 'normal', 0),
  ('old_notebook', 'npc', 'cat_detective', '墨墨的旧账本', '封皮磨破的笔记本，里面记着镇上每个人的可疑行为。', 1, 1, 'normal', 0),
  ('mayor_seal', 'npc', 'mayor', '镇长印章', '一枚朱红印章，盖下去就算官方文书。镇长从不离身。', 1, 0, 'normal', 0)
ON DUPLICATE KEY UPDATE
  `name` = VALUES(`name`),
  `description` = VALUES(`description`),
  `quantity` = VALUES(`quantity`),
  `is_transferable` = VALUES(`is_transferable`);

-- ---------------------------------------------------------------- 任务模板
-- 任务本身不预置到玩家身上：玩家第一次触发主线时由后端创建
-- （见 engine.ensure_quests）。这里没有 seed_template 之类的占位行，
-- 否则玩家列表里会混进不属于任何玩家的任务，破坏玩家隔离。
