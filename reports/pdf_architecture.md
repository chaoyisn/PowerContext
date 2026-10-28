# 实现

`src/powercontext/sources/pdf_pages.py` 使用 pypdf strict reader 和空密码解密，逐物理页提取，构造完整 tuple 后返回；失败转为 ValueError。Source 使用 captured 模型保留页面输入，标准投影保存指定三个 metadata 字段。检索使用 scoped Memory FTS 的多个查询候选、倒数排名融合，调用 memory.get 校验并按来源去重。没有外部模型或自建数据库。短语切分和排名是启发式，尚无合法标注评测证明达到隐藏召回阈值。
