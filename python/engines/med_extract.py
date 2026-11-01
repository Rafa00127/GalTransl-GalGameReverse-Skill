# SPDX-License-Identifier: GPL-3.0-only
"""MED extract and pack into new directories; strict CP932 script text only.

Both container profiles are handled: plaintext ``MDN0`` and ``MDE0``, whose
members use the additive member schedule. An ``MDE0`` key is always explicit
(``--key``); it is never derived, guessed or copied into the workspace, which
stores only its SHA-256. For Chinese use common.jis_workflow around this writer
and its actual readback. No game execution, in-place writes or runtime
installation.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import stat

from ..archives import med as archive
from ..common.binary import FormatError
from ..common.contract import dump_rows, load_json, sha256
from ..common.safety import _check_existing_ancestors, validate_names, write_new_tree, validate_new_tree_destination
from . import med_script as script


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def read_bounded(path, limit=16 << 20):
    path = Path(path)
    _check_existing_ancestors(path.parent)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or getattr(info, "st_file_attributes", 0) & 0x400:
        raise FormatError(f"MED workspace input must be an ordinary unlinked file: {path}")
    if info.st_size > limit:
        raise FormatError("MED workspace file exceeds budget")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) != info.st_size:
        raise FormatError("MED workspace file changed size")
    return data


def parse_key(text):
    """Parse an explicit member key given as ``hex:..`` or ``ascii:..``."""
    if text is None:
        return None
    head, sep, value = text.partition(":")
    if not sep:
        raise ValueError("MED member key needs a 'hex:' or 'ascii:' prefix")
    if head == "hex":
        try:
            key = bytes.fromhex(value)
        except ValueError as exc:
            raise ValueError("MED hex member key is malformed") from exc
    elif head == "ascii":
        try:
            key = value.encode("ascii")
        except UnicodeError as exc:
            raise ValueError("MED ascii member key must be ASCII") from exc
    else:
        raise ValueError("MED member key prefix must be hex: or ascii:")
    return archive.check_key(key)


def member_plain(entry, data, key):
    """Decoded member bytes; ``key`` is None only for the plaintext profile."""
    raw = data[entry.offset:entry.offset + entry.size]
    return raw if key is None else archive.transform_member(raw, key)


def container_profile(data, key):
    """Return (container id, coded flag) and reject a key/profile mismatch."""
    container = archive.profile(data)
    coded = container == archive.ENCRYPTED_PROFILE
    if coded and key is None:
        raise FormatError("MDE0 members use the additive member schedule; pass --key hex:.. or ascii:..")
    if not coded and key is not None:
        raise FormatError("member key given for a plaintext MDN0 archive")
    return container, coded


def member_info(entry, data):
    detail = script.summary(data)
    return {"name": entry.name, "size": len(data), "sha256": sha256(data), **detail,
            "json": entry.name + ".json" if detail["rows"] else None,
            "status": "exported" if detail["rows"] else "no-display-text"}


def extract(source, output, key=None):
    source, output = Path(source), Path(output)
    validate_new_tree_destination(output)
    validate_names([source.name])
    data, entries = archive.read_archive(source)
    container, coded = container_profile(data, key)
    if coded:
        key = archive.check_key(key)
    files = {"original/" + source.name: data, "gt_output/.keep": b""}
    members, rebuilt, roles = [], {}, Counter()
    for entry in entries:
        raw = member_plain(entry, data, key)
        try:
            rows, manifest = script.export(raw)
            result = script.rebuild(raw, rows, manifest)
            if result != raw:
                raise FormatError("MED no-edit writer changed original bytes")
            rebuilt[entry.name] = result
            info = member_info(entry, raw)
        except (ValueError, UnicodeError) as exc:
            raise FormatError(f"MED {source.name}:{entry.name}: {exc}") from exc
        members.append(info)
        roles.update(info["roles"])
        files["original/scripts/" + entry.name] = data[entry.offset:entry.offset + entry.size]
        if rows:
            files["gt_input/" + info["json"]] = dump_rows(rows)
            files["metadata/" + info["json"]] = json_bytes(manifest)
    packed = archive.rebuild(data, rebuilt, key)
    if packed != data:
        raise FormatError("MED no-edit archive writer changed original bytes")
    files["rebuilt/roundtrip/" + source.name] = packed
    report = {"engine": "med", "profile": script.PROFILE, "archive": source.name,
              "container": container, "member_coding": "additive-key" if coded else "none",
              "key_sha256": sha256(key) if coded else None,
              "member_sha256_over": "decoded" if coded else "stored",
              "source": str(source), "archive_size": len(data), "archive_sha256": sha256(data),
              "script_encoding": "cp932", "json_encoding": "utf-8",
              "members": members, "member_count": len(entries),
              "json_files": sum(bool(m["rows"]) for m in members), "rows": sum(roles.values()),
              "roles": dict(roles), "identity_verified_members": len(entries),
              "identity_verified_archive": True, "runtime_verified": False,
              "scope": "op01 followed by op00; op0d bracketed names until page end; op0a choices; op2c titles",
              "excluded": {"unpaired_op01_literals": sum(
                  int(m["opcodes"].get("01", 0)) - m["roles"].get("message", 0) - m["rule_literals"] for m in members),
                  "rule_definition_literals": sum(m["rule_literals"] for m in members)}}
    files["reports/extraction.json"] = json_bytes(report)
    files["README.txt"] = (
        "MED 文本工作区\n\n"
        f"容器：{container}；original/scripts 保存容器内的原始成员字节。\n"
        + ("该容器成员按显式密钥编码；work 区不保存密钥，只记录其 SHA-256。\n" if coded else "")
        + "gt_input：UTF-8 JSON，姓名在正文上方；只含非空脚本。\n"
        "gt_output：译文按同名放回后告诉 agent，由 agent 校验、回写并生成新归档。\n"
        "保持顺序、姓名字段和控制符；换行可减少但不可新增，物理分行保持独立，不合并条目。\n"
        "同一姓名指令覆盖的多条正文须使用一致译名；关联见 metadata 中的 name_frame。\n"
        "章节/存档标题也已导出，角色见 metadata；不要修改 original、metadata 或 gt_input。\n"
        "original 保存原归档和脚本；rebuilt/roundtrip 经过完整读写并逐字节核对。\n"
        "中文路线：优先把引擎读取的字符集改为 GBK/UTF-8 并重建字库；"
        "确认加载路径不支持时才退回公共 JIS 代理映射 + hook/替换字体。\n"
        "不假设 patch.med 会被读取；交付同名完整归档，部署需备份原件并另行确认。\n"
        "离线回读不等于游戏显示已验证；先测试开场少量文本。\n").encode("utf-8")
    write_new_tree(output, list(files.items()))
    return report


def pack(workspace, output, key=None):
    workspace, output = Path(workspace), Path(output)
    validate_new_tree_destination(output)
    report = load_json(read_bounded(workspace / "reports/extraction.json"))
    if report.get("engine") != "med" or report.get("profile") != script.PROFILE:
        raise FormatError("unsupported MED workspace profile")
    container = report.get("container")
    if container not in (archive.PLAIN_PROFILE, archive.ENCRYPTED_PROFILE):
        raise FormatError("MED workspace lacks a known container profile")
    coded = container == archive.ENCRYPTED_PROFILE
    if coded:
        if key is None:
            raise FormatError("MDE0 workspace needs the explicit member key (--key)")
        key = archive.check_key(key)
        if sha256(key) != report.get("key_sha256"):
            raise FormatError("MED member key differs from the extraction key")
    elif key is not None:
        raise FormatError("member key given for a plaintext MDN0 workspace")
    name = report["archive"]
    if validate_names([name]) != [name] or "/" in name or "\\" in name:
        raise FormatError("MED archive filename must be flat")
    raw, entries = archive.read_archive(workspace / "original" / name)
    if sha256(raw) != report["archive_sha256"] or len(raw) != report["archive_size"]:
        raise FormatError("MED original archive hash/size differs")
    if archive.profile(raw) != container:
        raise FormatError("MED container profile differs from the workspace")
    expected_info = [member_info(e, member_plain(e, raw, key)) for e in entries]
    if expected_info != report["members"]:
        raise FormatError("MED member inventory differs from original parse")
    _check_existing_ancestors(workspace / "gt_output")
    output_paths = list((workspace / "gt_output").iterdir())
    if len(output_paths) > archive.MAX_ENTRIES:
        raise FormatError("MED translation directory exceeds budget")
    available = {p.name for p in output_paths if p.suffix.lower() == ".json"}
    validate_names(list(available))
    expected_files = {m["json"] for m in expected_info if m["rows"]}
    # Unmatched names do not get guessed onto another script.
    unmatched = sorted(available - expected_files)
    modified, changed, readback, translated = {}, [], {}, []
    for entry, info in zip(entries, expected_info):
        data = member_plain(entry, raw, key)
        rows, manifest = script.export(data)
        target = rows
        if rows:
            filename = info["json"]
            if (load_json(read_bounded(workspace / "gt_input" / filename)) != rows
                    or load_json(read_bounded(workspace / "metadata" / filename)) != manifest):
                raise FormatError(f"MED original JSON or manifest changed: {filename}")
            if filename in available:
                target = load_json(read_bounded(workspace / "gt_output" / filename))
                translated.append(filename)
        result = script.rebuild(data, target, manifest)
        modified[entry.name] = result
        if result != data:
            changed.append(entry.name)
    packed = archive.rebuild(raw, modified, key)
    # Read actual rebuilt member offsets, not in-memory replacement rows.
    import io
    for entry in archive.index(io.BytesIO(packed), len(packed)):
        data = member_plain(entry, packed, key)
        rows, _ = script.export(data)
        if rows:
            readback["readback/gt_input/" + entry.name + ".json"] = dump_rows(rows)
    result = {"engine": "med", "profile": script.PROFILE, "archive": name,
              "container": container, "member_coding": "additive-key" if coded else "none",
              "sha256": sha256(packed), "changed_members": changed,
              "translated_json_files": translated, "unmatched_translation_files": unmatched,
              "verified_members": len(entries), "verified_json_files": len(readback),
              "runtime_verified": False, "script_encoding": "cp932"}
    files = {name: packed, **readback, "reports/rebuild.json": json_bytes(result),
             "README.txt": (
                 "MED 完整归档回写结果\n已重新解析归档和脚本，核对译文及非文本结构。\n"
                 "这是同名完整归档，不是 patch 增量包。备份后按原位置部署，勿覆盖备份。\n"
                 "本工具未安装文件或运行游戏，尚需核对加载和字形显示。\n"
                 "已有 GBK/UTF-8 字库补丁时直接使用；走公共 JIS 流程时请部署其 finalize 结果与配套配置。\n").encode("utf-8")}
    write_new_tree(output, list(files.items()))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    key_help = "member key of a coded MDE0 container: hex:4b49.. or ascii:.."
    command = commands.add_parser("extract")
    command.add_argument("source")
    command.add_argument("output")
    command.add_argument("--key", help=key_help)
    command = commands.add_parser("pack")
    command.add_argument("workspace")
    command.add_argument("output")
    command.add_argument("--key", help=key_help)
    args = vars(parser.parse_args())
    action = args.pop("command")
    try:
        args["key"] = parse_key(args["key"])
    except ValueError as exc:
        parser.exit(2, f"invalid member key: {exc}\n")
    result = extract(**args) if action == "extract" else pack(**args)
    print(json.dumps({k: v for k, v in result.items() if k != "members"}, ensure_ascii=True))


if __name__ == "__main__":
    main()
