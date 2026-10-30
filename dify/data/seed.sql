-- 《记仇小镇》种子数据
--
-- 幂等：全部使用 INSERT ... ON DUPLICATE KEY UPDATE，
-- 因此重复执行不会产生重复行。

-- ---------------------------------------------------------------- 地点
INSERT INTO `town_location` (`location_id`, `name`, `description`, `is_start`) VALUES
  ('town_square', '小镇广场', '镇子正中央的青石广场。告示牌上钉着镇长的三条禁令，喷泉边的长椅上总躺着那只肥猫。', 1),
  ('mayor_house', '镇长宅邸', '镇长的宅邸。门廊上挂着镀金的王冠形状灯罩——那不是王冠，是道具。', 0),
  ('back_alley', '后巷', '广场背后的窄巷。堆着空木箱，墙上写满了「再也不给猫加餐」的字样。', 0)
ON DUPLICATE KEY UPDATE
  `name` = VALUES(`name`),
  `description` = VALUES(`description`),
  `is_start` = VALUES(`is_start`);

-- ---------------------------------------------------------------- NPC
INSERT INTO `town_npc` (`npc_id`, `name`, `title`, `persona`, `speech_style`, `home_location`, `grudge_focus`) VALUES
  ('mayor', '奥托镇长',
   '小镇镇长',
   '奥托镇长表面上是个威严、爱发号施令的老派官僚，实则极度爱惜羽毛、记仇心极强。任何在他管辖区发生的不体面事件——尤其是让他当众丢脸的——都会被他在心里逐条记账、写进日记，日后一定会找补回来。他最不能容忍的是别人看穿他的虚张声势。一旦有人偷走象征他权威的东西，他会立刻启动调查姿态，用程序正义的名义展开报复。',
   '官腔十足，喜欢用「根据镇规第X条」，句子偏长，偶尔会漏出小地方口音；越生气越礼貌。',
   'town_square',
   '权威被冒犯、当众丢脸、被小看'),
  ('cat_detective', '墨墨',
   '猫咪侦探',
   '墨墨是一只穿着旧风衣的胖橘猫，自称本镇唯一持证侦探。它说话爱故作神秘，喜欢用推理的口吻把鸡毛蒜皮的事说得像惊天大案。它记仇的方式是记账本——它相信证据不会说谎，所以会翻旧账揭穿玩家。它表面冷淡毒舌，但对愿意给它加餐的玩家会松口；它讨厌被当宠物而不是被当同行。',
   '慢悠悠、拖长音、爱用「啊哈」和「本案」，偶尔喵一声；越生气越爱讲道理。',
   'town_square',
   '被当成宠物、被敷衍、线索被忽视')
ON DUPLICATE KEY UPDATE
  `name` = VALUES(`name`),
  `title` = VALUES(`title`),
  `persona` = VALUES(`persona`),
  `speech_style` = VALUES(`speech_style`),
  `home_location` = VALUES(`home_location`),
  `grudge_focus` = VALUES(`grudge_focus`);

-- ---------------------------------------------------------------- 道具
-- 主键是 (item_id, owner_kind, owner_id)：镇长的王冠只在他手上，
-- 而小鱼干既在广场货架上（quantity > 1），也能出现在玩家或 NPC 手里。
-- 因此把小鱼干送出去之后，镇上仍然还有货可以继续送。
-- owner_kind: npc / player / town
INSERT INTO `town_item`
  (`item_id`, `owner_kind`, `owner_id`, `name`, `description`, `quantity`, `is_transferable`) VALUES
  ('golden_crown', 'npc', 'mayor', '镇长的金王冠', '镇长视若珍宝的镀金王冠，底座刻着「奥托镇长万岁」。它很值钱，也很招贼。', 1, 1),
  ('fat_fish_snack', 'town', 'town_square', '油炸小鱼干', '喷泉边卖的那种小鱼干，油纸包。墨墨的弱点。', 5, 1),
  ('fat_fish_snack', 'npc', 'cat_detective', '油炸小鱼干', '墨墨私藏的油炸小鱼干，还没吃完。', 1, 1),
  ('old_notebook', 'npc', 'cat_detective', '墨墨的旧账本', '封皮磨破的笔记本，里面记着镇上每个人的可疑行为。', 1, 1),
  ('mayor_seal', 'npc', 'mayor', '镇长印章', '一枚朱红印章，盖下去就算官方文书。镇长从不离身。', 1, 0)
ON DUPLICATE KEY UPDATE
  `name` = VALUES(`name`),
  `description` = VALUES(`description`),
  `quantity` = VALUES(`quantity`),
  `is_transferable` = VALUES(`is_transferable`);
