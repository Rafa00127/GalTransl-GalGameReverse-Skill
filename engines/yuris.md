# YU-RIS：YPF 解包、YBN 分区 XOR 与 ysc.ybn

## 能力边界
- 引擎 ID：`yuris`。
- 参考模块：[python/engines/yuris.py](../python/engines/yuris.py)。
- 归档模块：[python/archives/yuris.py](../python/archives/yuris.py)，实现指定版本/方案的 YPF 索引、选中成员读取及 raw/zlib 解码。
- 实现 YSTB 四分区 XOR、SJIS 感知的控制字节转换和 YSCM 命令表。
- 通用模块没有完整表达式 VM 或自动密钥推断。
- **v482（0x1E2）**支持提取、回填及 YPF 模板重封（公共模块，见下节）。
- **v490 / v495 + YPF 0x1EF（YU-RIS 0.495）也已实测通过**，但**回填走松散 `Data\ysbin\*.ybn` 覆盖，
  不重封 YPF**；实现在 `项目-好色精灵之森G/work/`，不是公共模块。详见下面「版本支持矩阵」。
- **其它版本字只有解析**：`Scenario`/`commands_from` 接受 234–490 并报告 `version`，但回填仍只对
  v482 生效（`serialize` / `rebuild_script` 拒绝其它版本）。放开范围的依据是第三方工具
  （翻译肋手 v4.9D 反编译）用同一套 `<HHII>` 描述符读取 234–490，**这只是解析边界，不是
  “布局已证实相同”**；工作区提取遇到非 482 脚本记录为 `unsupported_version`，成员按原字节保留，不出 JSON。
- **YDG 图片与 CP932 字库页面**：支持格式 100 的 QOI/WebP 分块、PNG 模板回封及显式网格字库重建，流程和依赖见 [YDG 与字库](yuris/ydg.md)。图片资源与 YBN 语义分开处理；字库映射复用公共 JIS 流程。

## 版本支持矩阵（以实测为准）

| 组合 | 提取 | 回填 | 实现在哪 |
|---|---|---|---|
| YPF `0x1E2` + YSTB 482 | ✅ | ✅（含 YPF 模板重封） | 公共模块 `yuris_482.py` / `yuris_text.py` / `yuris_extract.py` |
| YPF `0x1EF` + YSTB 490 / 495（YU-RIS 0.495） | ✅ | ✅ **松散 `Data\ysbin\*.ybn` 覆盖**，不重封 YPF | `项目-好色精灵之森G/work/`（`extract_ysbin.py`、`build_patch.py`、`ypf.py`） |
| 其它 234–490 | 仅解析 | ✗ | 公共模块 parse-only |

**不要混用**：公共 `python/engines/yuris_text.py` 目前 `parse` 只放到 234..490、`serialize` 只到 482，
**v495 会直接抛 `outside 234..490`**。要跑 490/495，先照子项目那份实现补进公共模块，别拿公共模块硬跑。

**0x1EF + 490/495 的两条关键差异**（与 482 不同的地方）

- **不用重封 YPF**：引擎优先读松散的 `Data\ysbin\*.ybn`（实测：只放 2 个改过的 `.ybn` 即生效），
  所以 1.5 GB 的 `data.ypf` 原封不动。这也意味着 **YPF 0x1EF 的重封装仍未实现**，别宣称支持。
- **YSTB 四区 XOR key 相同（`0x96AC6FD3`），但值区共享/子串重叠更常见**：回填必须保留原值区
  全部字节、把新值追加到池尾、只更新该描述符的 `size/offset` 与头部值区长度（偏移 20），
  绝不重排，否则会破坏未知的流程目标引用。

**名字机制（GBK 路线下必须三者同写）**：引擎判「这句有没有人名」是拿**名字表键、`es.CHAR.NAME.MARK.SET`
标记、正文三者的字节编码**做比较（不是比 Unicode）。所以 GBK 汉化时名字键、标记、正文要一起写成 GBK，
只改正文会导致拆行失败、名字窗不出。细则见 `项目-好色精灵之森G/docs/好色精灵之森G-汉化技术笔记.md` §6。

## v482 工作流

| 层 | 实现与范围 |
|---|---|
| v482 YPF | [yuris_482.py](../python/archives/yuris_482.py)：索引、Murmur2 校验、有界解压、模板重封 |
| v482 YBN | [yuris_text.py](../python/engines/yuris_text.py)：WORD、单字符串 EVAL、姓名定义与选项、独立 manifest、追加式回填 |
| 工作区 | [yuris_extract.py](../python/engines/yuris_extract.py)：`extract` / `rebuild` CLI |
| 验证 | [test_yuris_482.py](../tests/test_yuris_482.py)、[来源记录](../provenance/yuris-482.json) |

### 必须区分的格式细节

- YPF header 的版本为 `0x1E2`，名字 XOR key 为 `FF`，长度置换为 `SWAP_TABLE_00`。记录为 `u32 name_hash / u8 name_length / name / u8 type / u8 packed / u32 raw_size / u32 stored_size / u64 offset / u32 data_hash`。名字及压缩流校验均为 **Murmur2(seed=0)**，不是 CRC32/Adler32。
- **不要用通用 reader 的 `extra_header_size=4` 假装支持该布局**：那会把 offset 的高四字节误读成 checksum，把真正的 checksum 当 extra。v482 使用独立 reader，并逐成员核对两种 Murmur2。
- 原归档索引顺序与物理存放顺序不同。writer 按原物理顺序重建，保留名字字段、目录顺序、间隙及尾部不透明数据，更新存储长度、原长度、64 位偏移、Murmur2。未改成员保留原压缩流；重压缩不作为原文往返的必要条件。
- `ysc.ybn` 版本同为 482，命令数以头部声明为准。命令表后还有诊断 cstring 和最后 **256 字节不透明表**，不是损坏的尾部；`read_command_list(..., allow_message_tail=True)` 仅在此版本验证该布局。整个 YSCM 保持原字节，尾部不交给翻译器。
- YSTB 分区 XOR key 为 `0x96AC6FD3`（小端字节 `D3 6F AC 96`）。这是当前 profile 的参数；其他输入须以完整命令、分区和属性结构确认，不能仅靠 XOR 自反性判断 key。
- 属性 ID 不是唯一键：LET、声明和流程控制重复使用 ID 0，类型高字节也有标志。IF/ELSE/LOOP 后续 type=0 的描述符是**指令目标和池位置**，不能把它当长度、偏移的字符串。这会制造“越界”假象，更不能用它去切分全文。
- 原值区有共享和子串重叠。writer **保留原值区全部字节**，每个修改过的文本属性单独追加新值，只更新该描述符的长度/偏移和值区总长。指令、其他属性、流程目标和行号不变，避免移动整个字符串池后破坏未知表达式引用。重新解析检查全部目标文本及所有非目标属性。

### 对话与显示文字

- raw `WORD` 作为可见文字导出，空 WORD 和空 `_` 不导出。`_`（EVAL）仅支持 YSCM 第一个参数元数据为字符串表达式、且指令只有一个 type=3 参数的完整字符串字面量；空字面量不导出。多参数、动态或组合表达式拒绝，不执行 VM，也不猜片段拼接规则。
- `【姓名】正文` 分成 `name` 与 `message`，回填恢复括号；正文引号、原有空格与换行保留，不自动排版。
- `GOSUB ES.CHAR.NAME` 中第一个参数为调用目标，第二个参数（ID 33）为角色键，第三个参数（ID 34）为显示名；只导出第三个参数作为独立姓名定义行（`message` 字段），角色键及后续参数保持原字节。布局不符时拒绝，不沿用选择参数的遍历规则。`ES.SEL.SET` 导出 ID 33..48 的字面量 PSTR 选项，到空参数停止；运行时显示仍须单独验证。
- 姓名/选项表达式必须是完整 `4D + u16长度 + 引号包围的字面量`；回填更新内层 u16 长度。未知组合表达式不会当普通文字替换。
- 已有 UIF `character_substitution` 时，提取正向还原显示文字，回填反向映射并严格 CP932 编码，再验证正向还原一致。无法表示的新字拒绝，须另行准备公共 JIS 方案；已启用的 tunnel decoder 不支持。
- EF 控制序列转换、保护和回填仍使用下文的规则；译文必须保留 `\p/\c/\u` 的顺序与数量。换行可以比原文少，但不能新增或跨这些控制码移动。
- 单字符串 EVAL 同样可拆分 `【姓名】正文`，回填保留字面量封装并更新内层长度。字段语义来源见 [文本字段来源](../provenance/common-text-fields.json)。
- 当前 manifest 参考标识为 `yuris_text/2`。旧提取目录须从哈希通过的原始数据重新导出到新目录；新增/修正的字段会改变条数或定位，不能修改旧 manifest 或按条数猜配译文。

### 可复现命令与产物

在技能根目录运行；路径仅作示例，`<输出目录>` 应是游戏内新建的 `<游戏名>_extract`，可复用已存在的普通空目录，父目录须已存在；已有非空目录不能覆盖。

```text
python -m python.engines.yuris_extract extract "<游戏目录>" "<输出目录>" --archive pac/update1.ypf --loose ysbin --uif-config uif_config.json --reference-archive pac/ysbin.ypf --reference-archive update1.ypf --smoke-test
```

`--archive` 明确指定模板，`--loose` 明确指定本次文本基准；成员集合与 YSCM 必须一致。不自动猜测加载优先级、合并冲突文件或回溯扫描旧提取目录。没有已有字符映射时省略 `--uif-config`。

- `gt_input/`：按场景名生成平铺 JSON，无目标文字的场景和配套文件不产生空 JSON。
- `gt_output/`：接收同名、同顺序译文；测试译文只放 `reports/smoke-translation/`，不混入这里。
- `original/game/`：原始包、完整松散 YBN、YSCM 和可选 UIF 配置；`metadata/` 保存重新解析可核对的描述符身份及哈希。
- `rebuilt/roundtrip/`：场景经 parser/writer、原归档经容器 writer 重建后的原文往返结果，配套文件保留。
- `rebuilt/current/ysbin.ypf`：按选定松散基准生成的完整包，须与松散原件逐成员比对，不与原更新包往返混淆。
- `rebuilt/smoke-test/`：可选的变长测试脚本和完整包；重新提取验证文本、描述符、原池、指令及行号。
- `reports/extraction.json`：来源哈希、基准选择、逐成员状态、包间差异及验证结果。

译文按同名文件放回 `gt_output` 后告诉 agent，由 agent 校验并回写：

```text
python -m python.engines.yuris_extract rebuild "<输出目录>" "<输出目录>/rebuilt/translated-01"
```

输出新目录含松散 `ysbin/` 和完整 `ysbin.ypf`。缺译文的成员保留**选定松散基准**，未知 JSON 文件名拒绝；源文件、原文 JSON 或 manifest 变化也拒绝。没有启动游戏或验证字体、加载优先级与排版，CLI 不安装这些产物。

## 识别证据
- YBN 不是单一格式：`YSTB` 是场景，`YSCF` 是配置。
- `ysc.ybn` 的 `YSCM` 是命令字典，不应当作普通场景翻译。
- VN 在加载场景前会读取同目录的 `ysc.ybn`。
- `.ypf` 是常见资源容器，以 `YPF\0` 签名及成员结构单独核验，不与场景 `YSTB` 混为一层。
- 仅找到可读 WORD 或日文不能证明文件已正确解密。
- 代码数量、四个分区长度和总大小应同时成立。

## 格式方言
- YSTB 头长 0x20，含版本、指令数与四个分区长度。
- 四区依次是指令、属性描述符、属性值、行号。
- 本参考要求指令区大小等于指令数乘四。
- XOR key 按小端四字节循环，并在每个分区重新从 key[0] 开始。
- 不能把从 0x20 到 EOF 的全部 bytes 当作一个不间断 key 流。
- YSCM 的命令 ID 是字典顺序，而不是跨游戏固定常量。
- 命令后有 u8 属性数，各属性为 cstring 名字 + 两字节元数据。
- 本参考保留重复属性项位置与元数据，不用字典悄悄覆盖属性 ID。

## 容器到剧本路线
1. 先处理 YPF 容器，再按成员签名分出 YSTB/YSCM/YSCF。
2. 使用本页的 YPF 接口读取目录与选中成员；源码依据为 GARbro-Mod `ArcFormats/YuRis/ArcYPF.cs`。
3. 保持场景与同版本 ysc.ybn 配套，不复用另一作品的命令编号。
4. 密钥需要独立证据，再做分区 XOR 和结构验证。
5. 只有完整属性/表达式解析器证明范围后才可设计变长回填。
- 通用模块没有 YPF writer；v482 的独立 writer 见上节。两条路线都不自动寻找密钥或安装外部工具。

## 实测方言：0.495（ルネ 2025-12，`YPF 0x1EF` / `YSTB 490,495`）

由《スケベエルフの森へG》实测（证据与脚本：`Galgame_AI/项目-好色精灵之森G/work/`）。与 v482
**同构**，但版本字不同，现有模块的版本白名单会直接拒绝，需要按下列参数显式放开：

- **YPF `0x1EF`**：记录布局与 `0x1D9` 族完全一致——`extra_header_size=4`、`SWAP_TABLE_00`、
  名字每字节 XOR `0xFF`；名字哈希是 **Murmur2(seed=0)** 而非 CRC32（5024 条全部核对通过）。
  `min(offset) == index_end`、尾部有若干不透明字节，可作布局自证。实现见项目 `work/ypf.py`。
- **YSTB 490 / 495**：头 0x20、四区（指令/描述符/属性值/行号）、描述符 `<HHII`、指令 `<BBH`，
  与 v482 相同；四区各自从 key[0] 重起算的 XOR，key 实测 `0x96AC6FD3`。v490 与 v495 同 key。
- **YSCM 495**：命令表结构与 482 相同（自身版本 495），尾部同样是「诊断 cstring + 256 字节表」。
  该游戏的命令 ID：`WORD=106`、`_=110`、`GOSUB=44`、`IF=45`、`ELSE=11`、`LOOP=56`。
- **回填**：v482 的「保留原值区 + 追加新值 + 只改该描述符 size/offset + 更新值区长度（偏移 20）」
  在 490/495 上同样成立（实测 15,020 条回填、10 万+ 未触及属性逐字节一致）。
- **坑**：`IF/ELSE/LOOP` 的流程目标描述符里的 `size` 是「指令序号」，其 `offset+size` 可以**超过**
  值区长度。取这类描述符的切片会读到池尾截断的结果，追加新值后长度变化 → 自检里出现假
  「未触及属性被改了」。必须先把 `control_targets` 排除，`value()` 对它们直接抛错。
- **名字窗（人名替换）**：`yst00086.ybn` 这类**独立人名表脚本**用 `es.CHAR.NAME`(参数 33 键 /
  参数 34 显示名，显示名为空 = 玩家输入的名字) 登记角色名，`es.CHAR.NAME.MARK.SET` 用 `「『（`
  注册分界符；取文本流程调 `es.TX.CHARNAME.CHK` 判中后 `es.TX.NAME.SHOW` 把名字画进名字窗、
  正文只留 `「台词」`。**判中要求「键 + 标记 + 正文」三者字节编码一致**（不是比较 Unicode）：
  纯 CP932 原版成立，三者统一换成 GBK 也成立；只改其中一两项就一定不拆行。换编码的翻译必须
  把参数 33 和 `MARK.SET` 的字面量一起改成目标编码，否则玩家名字永远不显示。
- **字符集路线**：`.data` 里有一张 256 字节「该字节起几字节构成一个字」的表（本例 VA
  `0x5b40c0`），被 `TextOutA(hdc,0,0,ptr, 1+table[*ptr])` 逐字栅格化时使用；把它改成目标
  编码的双字节范围即可整链切换（本作 SJIS→GBK 只改 66 字节）。字模是运行时 GDI 渲染，
  **没有点阵字库**要重建；字体名来自脚本 `FONT` 命令的字面量，换字体即可。

## YPF 版本与目录布局

`read_index` 必须显式提供 `version` 和文件名 `name_key`。头中实际版本必须一致，不能用文件后缀决定密钥。当前白名单覆盖上游代码中有明确布局线索的以下版本；其他版本先补证据与测试，不自动归入最近一档。

| version | 默认长度置换表 | 默认额外字段长度 |
|---|---|---|
| `0xDE` | `SWAP_TABLE_04` | 8 |
| `0xF7` | `SWAP_TABLE_04` | 0 |
| `0x122` | `SWAP_TABLE_00` | 0 |
| `0x12C` | `SWAP_TABLE_10` | 0 |
| `0x196` | `SWAP_TABLE_00` | 0 |
| `0x1D9` | `SWAP_TABLE_00` | 4 |
| `0x1F4` | 必须显式提供 `swap_table`，存在游戏专用表 | 4 |

- 魔数 `YPF\0`；`u32 version/count/directory_bound` 在 4/8/12，目录从 `0x20` 开始。
- 每条依次为：`u32 name_hash`、`u8 encoded_name_length`、加密名字、`u8 file_type`、`u8 packed`、`u32 unpacked_size/stored_size/absolute_offset/checksum`、额外字段。基础长度 `0x17 + name_length`，多字节名字按编码后的字节数计。
- 名字长度先与 `0xFF` XOR，再用置换表相邻两项互换；名字每字节 XOR `name_key`，默认严格 CP932。表必须是互不重复的字节对。
- `extra_header_size` 可按已证明方案显式传 0/4/8；保留到 `IndexEntry.extra`，不猜其中含义。`packed` 只接收 0/1；raw 成员声明的两种长度必须相同。
- 头部 `directory_bound` 是扫描上界，**不是可靠的 payload 起点**。上游 reader 从 `0x20` 起计剩余量，而 writer 写入包含头部的首数据偏移。本实现逐条扫描到 count，不为“填满 bound”而读入首成员；返回的 `index_end` 是实际目录末端。
- 上游 writer 写名字 CRC32、stored 流 Adler32，但 reader 忽略两者。默认保留字段，只有已确认该校验方言时启用 `verify_name_hash=True` / `verify_checksum=True`；校验失败不能自动换 key 后声称成功。
- 通用压缩仅支持 zlib。使用 Snappy 的方案、EXE/YSER overlay 定位、自动密钥推断和其他版本重封包仍缺失。归档返回解压后的原 YBN bytes，**不做 YSTB 的 ScriptKey XOR**。

## YPF 只读接口

```python
from pathlib import Path
from python.archives.yuris import read_index, read_member, decode_member

# proven_version/name_key 来自实际游戏的方案证据，不能照抄其他游戏的 key。
with Path("game/data.ypf").open("rb") as stream:
    index = read_index(stream, version=proven_version, name_key=name_key)
    entry = next(e for e in index.entries if e.name.lower().endswith(".ybn"))
    stored = read_member(stream, index, entry, max_stored_size=64 << 20)
    ybn = decode_member(entry, stored, compression="zlib", max_output_size=64 << 20)
# ybn 仍需检查 YSTB/YSCM/YSCF 签名及脚本自身的加密条件。
```

- `read_index` 默认 `max_entries=100000`、`max_index_size=16 MiB`（含头部），只读取目录，不按成员大小收费。
- `read_member` 返回所选成员的 stored bytes；`decode_member` 单独限制输出，校验 zlib 终止、尾部和声明长度，失败直接拒绝。
- 索引/读取都恢复流位置，支持合法短读。使用同一未改动的 seekable 二进制流；成员必须是该索引返回的原对象。检查文件总长度变化，但不检测同大小的原地修改，索引不是认证凭据。
- 路径穿越、Windows 保留名、大小写/Unicode 重名及文件/目录冲突拒绝。API 不写盘；批量解码需按剩余总预算逐项收紧上限，之后用公共 `write_new_tree` 写入新的输出目录。
- 通用归档算法出处、修改说明与验证等级见 [common-archives-v1.json](../provenance/common-archives-v1.json)；固定向量和异常输入见 [test_archives_common_engines.py](../tests/test_archives_common_engines.py)。v482 的读写接口见上节。

## 源码与算法对应
- 来源：`VNTextPatch-net8`，MIT。
- 提交：`d9c0fab7b72fdcf87d674ef12a84d3829c9188be`。
- 路径：`VNTextPatch.Shared/Scripts/Yuris/YurisScenarioScript.cs`。
- `ToggleScriptEncryption` 对应四区 XOR。
- `YurisControlCodesToStandard/StandardControlCodesToYuris` 对应控制转换。
- `YurisCommandList.cs/ReadCommand` 对应 YSCM 顺序字典。
- `VNTextPatch.Shared/Util/BinaryUtil.cs/Xor` 证明 key 字节序与循环行为。
- VN 的自动取 key 依赖首属性描述符假设，Python 不把该假设当通用保证。

## Python 接口与示例
```python
from python.engines.yuris import toggle_ybn_sections, convert_control_bytes
raw = b'A\xef\xf0B\xef\xf2'
standard = convert_control_bytes(raw)
assert standard == b'A\r\nB\\p'
assert convert_control_bytes(standard, to_yuris=True) == raw
assert toggle_ybn_sections(toggle_ybn_sections(ystb, key), key) == ystb
```
- `toggle_ybn_sections(bytes, u32_key) -> bytes`，头部不变。
- `convert_control_bytes(bytes, to_yuris=False) -> bytes` 只处理原始文本字节。
- `read_command_list(ysc_bytes) -> tuple[(命令名, 属性tuple), ...]`。
- 按返回序号找到 WORD、`_`、GOSUB 等 ID，不硬编码。

## name / message 映射
- VN 会合并部分 WORD/EVAL 属性，再尝试按日文引号解析姓名与正文。
- GOSUB 的 `ES.CHAR.NAME` 与 `ES.SEL.SET` 也可能产生文本。
- 本局部模块不输出假 name/message；它返回低层字节或命令结构。
- 接入完整提取器时必须保存参与合并的每个属性身份。
- 多人名与变量名保留为独立上下文，不应因合并而丢弃。
- 不能把 ysc 命令名、属性名或 `$str20` 类程序变量当译文替换。

## 回填、长度与控制码
- EF F0=换行，EF F2=翻页，EF F3=等待点击，EF F5=源码未明控制。
- 对应标准表示为 CRLF、`\p`、`\c`、`\u`。
- 逐 SJIS 字符移动，避免把双字节字符尾字节 0x5C 当反斜线控制。
- 未知 EF 控制码或不完整多字节字符直接拒绝。
- EF F5 只按源码可逆表示保留，不给它编造语义。
- 完整回填必须更新属性长度、全部属性值偏移、值区总长及后续区位置。
- 表达式字符串还有 4D/u16长度/引号约定，不能用裸文本替代。
- 本模块不执行这些全文件步骤，返回的局部结果不能直接覆盖整个 YBN。

## 部署条件
- 必須保存原 YSCM 与场景版本、key 来源和分区大小证据。
- 不用“XOR 两次等于原文”证明某个猜测 key 正确；任意 key 都有该性质。
- 先检查解密后的真实指令/属性边界，再谈翻译。
- 最终重加密与包写回必须属于经验证的完整流水线。
- 公共层统一处理原文件保护、目标目录与 manifest。

## 验证与缺口
- 合成测试故意使用非四字节对齐区长，验证每区 key 相位重置。
- 测试控制码往返、SJIS 0x5C 尾字节不误改与未知码拒绝。
- 测试 YSCM 顺序 ID、属性元数据及未知尾部拒绝。
- 测试位置：`tests/test_engines_primary.py` 中 `YurisTests`。
- SExtractor `src/extract_Yuris.py` 是另外的提取路径，不是本模块依赖。
- 其提交 `8d8d976fd04ae54e7c677705af937273d04a376a`，GPL-3.0。
- 完整表达式 VM、其他版本的属性回填/YPF 封包和商业运行验证仍缺失；v482 的特定方言支持以上节为准。
