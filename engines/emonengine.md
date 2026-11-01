# EmonEngine / EME：索引解密、LZSS 成员与剧本容器重封

## 模块分工

| 层 | 模块与接口 |
|---|---|
| 归档封包 | [archives/emonengine.py](../python/archives/emonengine.py)：`pack_scripts`、`zero_key_index` |
| 环窗口 LZSS | [archives/arcx.py](../python/archives/arcx.py)：`lzss`（同一 token 布局，`fill=0`、`start=0xFEE` 可直接解剧本体） |
| 索引解密、成员解包 | 未随包实现，按本文「索引解密」「成员解码」两节补写 |
| 剧本内对白与姓名 | 未随包实现；本页只到容器与成员层 |

## 能力分层

同一格式存在三种不同层级的实现，能力不可互相替代：

- **完整读取参考**：GARbro 的 `EmeOpener`/`LzssStream` 覆盖非零密钥、双段压缩、`LzssFrameSize=0` 未压缩成员与 subtype 5；本文的读取行为以它为准。
- **只写剧本、零密钥**：SExtractor `tools/EmonEngine/eme_pack.py`，密钥区恒写 40 个 0，压缩走原生扩展模块，只处理 subtype 3。
- **随包子集**：[emonengine.py](../python/archives/emonengine.py) 是上一项的标准库重写并加严校验，只接受「零密钥 + 单段 + `frame=0x1000` + 存储 init `0x12`」。

写入侧（索引再加密、成员压缩、offset 重算）只有本地移植实现覆盖，读取侧重实现应以上面第一条的对齐行为做对拍。

## 识别与范围

- 头 8 字节固定 `RREDATA `；末 4 字节为 u32 成员数。
- 尾索引之前有 40 字节密钥例程；例程全零时索引与 12 字节成员子头等效明文。
- 扩展名多为 `.eme`、`.rre`，但同引擎不同作品可能使用不同例程与不同的 subtype 分布，不能只看扩展名或厂商名。
- subtype 3 是剧本，4 是图片，5 是 T5 包装；只有 3 参与文本回填。
- 本页不把「零密钥剧本容器」扩大解释为「EME 完整支持」。

## 容器布局

| 区域 | 位置 / 长度 | 说明 |
|---|---|---|
| 文件头 | `0..8` | 固定 `RREDATA ` |
| 成员区 | `8 .. dataEnd` | 每个成员 = 12 字节子头 + 数据体 |
| 密钥区 | `dataEnd .. dataEnd+40` | 40 字节例程，全零即不加密 |
| 索引 | `dataEnd+40 .. 末 4 字节前` | 每条 `0x60`，逐条解密 |
| 成员数 | 末 4 字节 | u32 LE |

`dataEnd` = 明文长度 − 4 − count×0x60 − 40。

索引记录（解密后）字段：

| 偏移 | 类型 | 含义 |
|---|---|---|
| 0x00 | 0x40 字节 | 资源名，CP932，NUL 结尾 |
| 0x40 | u16 | `LzssFrameSize`；0 表示该成员未压缩 |
| 0x42 | u16 | 存储的 init；`frame≠0` 时实际写指针初值 = `(frame − 本值) % frame` |
| 0x44 | u32 | 常量 1（原档一致，重封沿用） |
| 0x48 | i32 | `SubType`：3 剧本 / 4 图片 / 5 T5 |
| 0x4C | u32 | 压缩长度 `Size` |
| 0x50 | u32 | 明文长度 `UnpackedSize` |
| 0x54 | u32 | 成员起点 `Offset`，指向 12 字节子头 |
| 0x58 | 8 字节 | 保留 |

**`Size` 不含 12 字节子头。** 成员实际跨度 = 下一成员 `Offset` − 本成员 `Offset`；最后一个成员到密钥区起点。按 `Size` 累加做重封会每个成员少算 12 字节。

## 索引解密

- 例程 40 字节：`routine[0..7]` 是 8 个 op 码，op 码 i 的 u32 密钥在 `routine[8+4*i]`。
- 解密按 i = 7 → 0 的顺序执行；加密是同组运算的逆序 + 逆运算，不能用解密再跑一遍凑合。
- 四个 op：
  - 1：逐 u32 XOR 固定密钥，自逆。
  - 2：链式 XOR，下一段的密钥取「上一段密文」（与缓冲区长度相关）。
  - 4：位重排，`shift += key` 后把第 i 位搬到 `((i+1)×key) & 31`；逆运算按同一目标位取回。
  - 8：字节置换，`x += key` 对长度取模后搬位（与缓冲区长度相关）。
- op 2 与 op 8 依赖缓冲区长度，因此**必须逐条按 0x60 解密**；把整块索引一次性解密会得到不同结果。
- 例程全零时四个 op 都不触发，索引就是明文；随包子集只走这条路。

## 成员解码

12 字节子头先用同一例程解密，再按 subtype 与 `LzssFrameSize` 分支：

- `LzssFrameSize == 0`：未压缩，明文 = 解密后的 12 字节子头 + 其后 `Size` 字节原样数据。
- 否则读子头 `u32@0` = `packed_size`（第二段长度），`i32@4` = 第二段明文长度：
  - `0 < 第二段明文长度 < UnpackedSize`：双段。第一段数据位于 `Offset+12+packed_size`，解出 `UnpackedSize − 第二段明文长度` 字节放在输出开头；第二段位于 `Offset+12`、长度 `packed_size`，解出「第二段明文长度」字节接在后面。
  - 否则单段：从 `Offset+12` 起解，输出到 `UnpackedSize` 为止。
- subtype 5（T5）：前 4 字节解密后 + 其后 `Size−4` 字节原样，不做 LZSS。
- subtype 4 及其他：按原始字节读取。

## LZSS 参数

- 4096 字节环窗口（`frame=0x1000`），写指针初值 `0xFEE`（对应存储 init `0x12`）。
- 控制字节在前，其后 8 个 token，低位先；bit=1 为字面量（1 字节），bit=0 为匹配（2 字节）。
- 匹配：`offset = lo | ((hi & 0xF0) << 4)`，`length = (hi & 0x0F) + 3`；拷贝允许自重叠（RLE）。
- 环窗口初值全 0；解码到声明的明文长度即止。
- [arcx.lzss](../python/archives/arcx.py) 的窗口、位序与 token 布局与本格式一致，可直接解单段剧本体。差别只有一条：它要求输入被完全消费，而单段成员达到 `UnpackedSize` 之后的剩余字节属于合法填充，遇到这种成员要放宽尾部检查。

## 回填与重封包

1. 只改 subtype 3。其他成员（含其 12 字节子头）按原偏移原字节搬运，`Size`/`UnpackedSize` 不动。
2. 剧本成员重封：明文整体压缩，子头写单段形式（12 字节明文全零，再按例程加密），`Size` = 压缩体长度、`UnpackedSize` = 明文长度。
3. 所有成员 `Offset` 从 8 起按「12 + 压缩体长度」重算，允许变长，不复用原 offset。
4. 索引重写后必须按 `0x60` 逐条再加密（密钥非零时）。`0x40..0x54` 按成员写回，`0x58` 起的保留区在同一档案内保持一致。
5. 存储 init 写回 `(frame − 实际 init) % frame`；沿用原档存储值最省事。
6. 陷阱：原 `LzssFrameSize == 0` 的成员若仍按第 2 步压成 LZSS，就必须同时把索引 `0x40` 改成 `0x1000`、`0x42` 改成 `0x12`。只压数据不改字段，引擎会按明文读压缩体。无法确认引擎行为时，这类成员保持原样最稳。
7. 双段成员（子头 `u32@0` 非零）重封成单段是合法流，但改变了引擎侧的读取分支，需实机确认。
8. 覆盖原档案前保留原始副本；offset 与索引尺寸一变，旧存档不会随之迁移。

## 对白与姓名

- EME 名是资源名，不是角色名；角色名仍要看剧本指令帧。
- 提取要先解码成员，再按 opcode 取会被显示的串（正文/姓名/标题/选项），跳过注释与资源 id。
- 在不掌握该作品剧本语义前，不要用「扫所有 NUL 串」的方式代替指令解析。

## 编码路线

容器不决定汉字入库路线。按全库顺序：先[改引擎字符集为 GBK/UTF-8](../guides/charset-replacement.md)，其次脚本层换编码，最后才走 [JIS 代理 + UIF](../guides/jis-substitution.md)。EME 侧要核对的是剧本解码器与字库，重封只负责把字节按同一压缩/加密参数写回。

## 部署先决条件

- 零密钥重封要求目标加载器接受全零例程；不能由其他档案推断所有作品都接受。
- 非零密钥、双段、subtype 4/5 与分段脚本不在随包支持范围。
- 索引尺寸只随成员数变化，可以整档覆盖；覆盖前备份原档案。

## 诚实边界

- 随包没有完整 EME 读取器：`zero_key_index` 只校验零密钥 + 单段 + 全字面量流的子集。
- 「索引解密」与「成员压缩」只有算法级描述，随包未实现，也未用真实档案做逐字节往返。
- 档案可以增大；缓冲区与加载器接受度未实机验证。

## Python 调用

在 skill 根目录可使用如下接口；变量均由调用方提供，示例不自动读写磁盘。

```python
from python.archives import emonengine
archive = emonengine.pack_scripts([("test.bin", b"synthetic")])
records = emonengine.zero_key_index(archive)
```

## 验证与交付检查

- 合成测试核对 subtype、成员起点、12 字节子头与未压缩长度。
- 生成流经独立 LZSS reader 还原；非零密钥会被拒绝。
- 合成测试：`python -B -m unittest discover -s tests -p test_engines_tools_a.py -v`。
- 真实档案的顺序是：解包 → 原样重封 → 逐字节比对 → 再回填译文；显示层另测。
- 「索引逐条加密」「`Size` 不含子头」「`Offset` 重算」三项要单独核对，只比文件大小或能打开不算验证。

## 出处与许可

- 直接依据：SExtractor 固定提交 `8d8d976fd04ae54e7c677705af937273d04a376a` 的 `tools/EmonEngine/eme_pack.py`，符号 `Arc.pack`、`Arc.encrypt`。
- 补充结构来源：GARbro-Mod 提交 `bc26d991ef5cdc0e1ecb32122ee9a48c3375750c` 的 `ArcFormats/EmonEngine/ArcEME.cs`、`ArcFormats/LzssStream.cs`（文件头 MIT），只作文档依据，不作为运行时导入。
- 参考改写按本仓库 GPL-3.0-only 分发；许可文本与逐文件来源见 `provenance/tools-a.json`。
- 改写去除路径/GUI/全局变量耦合，保留算法并加严边界；不加载原生扩展模块或外部可执行文件。
