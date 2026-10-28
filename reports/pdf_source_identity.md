# 页身份

对 `[document_id, document_sha256, page_number]` 使用确定性的紧凑 JSON ASCII 编码，再以 SHA-256 命名，长度固定。完整原字节 SHA-256 区分修订；document_id 不需要截断。Source read 返回原 PDFPageInput。投影内容为 document_id、换行、页文本，metadata 恰好为 document_id、document_sha256、page_number。测试覆盖长 Unicode ID、不同文档及不同页；公开验收覆盖修订、重复入库和读取。
