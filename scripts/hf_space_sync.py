#!/usr/bin/env python3
"""HFS v3.0 示例工具与同步脚本。

命令：
  init   创建或补全标准项目文件和用户级默认值（只生成 standard = "3.0"）
  check  静态对齐检查；旧标准（2.1/2.2）项目只读输出迁移差距报告
  info   显示项目地址、登录入口、键设置状态和事实源；永不显示值
  diff   比较本地登记、Space 设置、种子和实例配置；有差异返回 1
  push   从本地 env 文件推送已登记设置，并更新和读回种子
  pull   将实例配置回收到 local/hfs-sync-pulled/，绝不覆盖根种子

v3.0 是 breaking 标准：init/info/diff/push/pull 只接受 standard = "3.0"，
旧标准项目只能由 check 的差距审计只读读取，迁移按 README 配方人工完成。

init/check/info 仅依赖 Python 3.11+ 标准库。
diff/push/pull 另需 huggingface_hub==1.25.1、click==8.4.2
（后者是本脚本调用的 module HF CLI 的直接运行依赖）；
仅处理 YAML seed 时需要 PyYAML>=6.0。
diff/push/pull/info 不打印 secret 值；用户主动执行 init 时会显示新生成的标准登录值。
HF_TOKEN/GH_TOKEN 只作为本地控制凭据，不推 Space。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import secrets as pysecrets
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from huggingface_hub import HfApi


SUPPORTED_STANDARDS = {"3.0"}
DEFAULT_STANDARD = "3.0"
LEGACY_STANDARDS = {"2.1", "2.2"}
MANIFEST_ROOT_FIELDS = {
    "standard",
    "project",
    "space",
    "space_visibility",
    "bucket_visibility",
    "project_class",
    "target_role",
    "sovereignty",
    "lane",
    "version_source",
    "bucket_namespace",
    "local_only",
    "secrets",
    "optional_secrets",
    "variables",
    "env_file",
    "dist_bucket",
    "seed_file",
    "other_objects",
    "mount_config_bucket",
    "mount_config_object",
    "deviations",
    "compat",
}
STANDARD_KEYS = ("ADMIN_USERNAME", "ADMIN_PASSWORD", "OPS_TOKEN")
TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
DEFAULT_DIST_BUCKET = "hfs-dist"
DEFAULT_LOCAL_ONLY = {"HF_TOKEN", "GH_TOKEN"}
SOVEREIGNTIES = {"sovereign", "fork", "port"}
LANES = {"source", "artifact"}
VERSION_SOURCES = {"latest", "tag", "commit"}
PROJECT_CLASSES = {"preview", "production"}
TARGET_ROLES = {"primary", "rotation", "candidate", "restore"}
SPACE_VISIBILITIES = {"protected"}
BUCKET_VISIBILITIES = {"private"}
ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SAFE_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
SPACE_ID = re.compile(r"^(?:\w(?:[\w.-]*\w)?/)?\w(?:[\w.-]{0,94}\w)?$")
TEXT_KEY_VALUE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*[:=]\s*(.*?)\s*$")
URL_VALUE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s\"']+")
DSN_FIELD = re.compile(
    r"(?:^|[\s;])(?P<key>[A-Za-z][A-Za-z0-9_.-]*)\s*=\s*(?P<value>[^\s;]+)"
)
SENSITIVE_KEY_SUFFIXES = {
    "pass",
    "password",
    "passwd",
    "passphrase",
    "pwd",
    "token",
    "secret",
    "api_key",
    "apikey",
    "access_key",
    "secret_key",
    "private_key",
    "client_secret",
    "credential",
    "credentials",
}
SAFE_PLACEHOLDERS = {"__FROM_ENV__", "CHANGE_ME", "REPLACE_ME", "REDACTED", "<SECRET>"}
ANGLE_PLACEHOLDER = re.compile(
    r"^<[^<>]*(?:placeholder|secret|token|password|passphrase|api[-_ ]?key|"
    r"replace|change|example|sample|todo|value)[^<>]*>$",
    flags=re.IGNORECASE,
)
STRUCTURED_SEED_SUFFIXES = {".toml", ".json", ".yaml", ".yml"}
TEXT_SEED_SUFFIXES = {"", ".cfg", ".conf", ".env", ".ini", ".properties", ".txt"}
LITERAL_SECRET = re.compile(
    r"(hf_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})"
)
DEFAULT_WORDS = (
    "amber", "apple", "atlas", "bamboo", "birch", "breeze", "brook", "cedar",
    "cloud", "coral", "dawn", "delta", "ember", "fern", "field", "forest",
    "harbor", "hazel", "island", "jade", "lake", "lotus", "maple", "meadow",
    "mist", "moon", "ocean", "olive", "pine", "river", "stone", "willow",
)


class SyncError(RuntimeError):
    """可安全展示给用户的同步错误。"""


def forbidden_key_reason(name: str) -> str | None:
    """v3.0 禁止登记的旧式键名；返回原因，合法时返回 None。

    SMOKE_* 开头的键视为真实独立 smoke 身份，不在禁止之列；
    只有 产品前缀 + SMOKE 场景词（如 SOUWEN_SMOKE_BEARER_TOKEN）被禁止。
    """
    if name.startswith(("SHOWCASE_", "BOOTSTRAP_")) or "_SHOWCASE_" in name or "_BOOTSTRAP_" in name:
        return "包含已禁止的 SHOWCASE/BOOTSTRAP 场景词"
    if "_SMOKE_" in name:
        return "包含已禁止的 产品前缀 + SMOKE 场景词；真实独立 smoke 身份使用 SMOKE_ 开头"
    if name != "ADMIN_PASSWORD" and name.endswith("_ADMIN_PASSWORD"):
        return "禁止产品前缀管理员密码键；统一使用 ADMIN_PASSWORD"
    if name != "OPS_TOKEN" and name.endswith("_OPS_TOKEN"):
        return "禁止产品前缀运维键；统一使用 OPS_TOKEN"
    return None


def resolve_local_file(root: Path, value: Path, field: str) -> Path:
    root = root.resolve()
    candidate = value if value.is_absolute() else root / value
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SyncError(f"{field} 不能指向项目根以外：{value}") from exc
    return candidate


def validate_env_file_path(value: Any) -> str:
    relative = validate_object_path(value, "env_file")
    path = PurePosixPath(relative)
    if relative == ".env":
        return relative
    if len(path.parts) == 3 and path.parts[:2] == ("local", "hfs-targets") and path.suffix == ".env":
        return relative
    raise SyncError("env_file 只能是项目根 .env 或 local/hfs-targets/<profile>.env")


def reject_symlink_components(root: Path, relative: Path, field: str) -> None:
    current = root.resolve()
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise SyncError(f"{field} 不能包含 symlink：{relative}")


def secure_plaintext_file(root: Path, relative: Path, field: str) -> Path:
    reject_symlink_components(root, relative, field)
    path = resolve_local_file(root, relative, field)
    if not path.exists():
        raise SyncError(f"缺少 {path}；本地明文事实源必须先建立")
    if not path.is_file():
        raise SyncError(f"{field} 必须是普通文件：{relative}")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        path_stat = path.stat()
        owned_by_user = not hasattr(os, "getuid") or path_stat.st_uid == os.getuid()
        if not owned_by_user or not os.access(path, os.W_OK):
            raise SyncError(f"{field} 权限必须是 0600，且当前用户无法修正：{relative}")
        try:
            path.chmod(0o600)
        except OSError as exc:
            raise SyncError(f"{field} 权限必须是 0600，自动修正失败：{relative}") from exc
        print(f"已将 {field} 权限从 {mode:04o} 修正为 0600：{relative}")
    return path


def load_manifest(root: Path, manifest_file: Path = Path("hfs-dev.toml")) -> dict[str, Any]:
    path = resolve_local_file(root, manifest_file, "manifest")
    if not path.exists():
        raise SyncError(f"缺少 {path}；见规范第 8 节")
    try:
        with path.open("rb") as file:
            manifest = tomllib.load(file)
    except tomllib.TOMLDecodeError as exc:
        raise SyncError(f"{path.name} 解析失败：{exc}") from exc
    return manifest


def strip_env_inline_comment(value: str) -> str:
    quote: str | None = None
    escaped = False
    first_value = len(value) - len(value.lstrip())
    outer_quote = (
        value[first_value]
        if first_value < len(value) and value[first_value] in {'"', "'"}
        else None
    )
    outer_closed: int | None = None

    for index, character in enumerate(value):
        if escaped:
            escaped = False
            continue
        if character == "\\" and quote is not None:
            escaped = True
            continue
        if character in {'"', "'"}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
                if outer_quote == character and outer_closed is None:
                    outer_closed = index
            continue
        if character != "#" or quote is not None:
            continue
        follows_whitespace = index > 0 and value[index - 1].isspace()
        follows_outer_quote = (
            outer_closed is not None
            and not value[outer_closed + 1 : index].strip()
        )
        if follows_whitespace or follows_outer_quote:
            return value[:index].rstrip()
    return value


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise SyncError(f"{path.name} 第 {number} 行不是 KEY=VALUE")
        key, _, value = line.partition("=")
        key = key.strip()
        if not ENV_KEY.fullmatch(key):
            raise SyncError(f"{path.name} 第 {number} 行键名非法：{key!r}")
        if key in values:
            raise SyncError(f"{path.name} 中键名重复：{key}")
        value = strip_env_inline_comment(value).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def generated_default_value() -> str:
    words = [pysecrets.choice(DEFAULT_WORDS) for _ in range(3)]
    number = pysecrets.randbelow(90) + 10
    return "-".join([*words, str(number)])


def user_defaults_file() -> Path:
    return Path.home() / ".config" / "hfs-dev" / "defaults.env"


def secure_external_plaintext_file(path: Path, field: str) -> Path:
    if path.is_symlink():
        raise SyncError(f"{field} 不能是 symlink：{path}")
    if not path.exists():
        raise SyncError(f"缺少 {path}")
    if not path.is_file():
        raise SyncError(f"{field} 必须是普通文件：{path}")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        path_stat = path.stat()
        owned_by_user = not hasattr(os, "getuid") or path_stat.st_uid == os.getuid()
        if not owned_by_user or not os.access(path, os.W_OK):
            raise SyncError(f"{field} 权限必须是 0600，且当前用户无法修正：{path}")
        try:
            path.chmod(0o600)
        except OSError as exc:
            raise SyncError(f"{field} 权限自动修正失败：{path}") from exc
        print(f"已将 {field} 权限从 {mode:04o} 修正为 0600：{path}")
    return path


def ensure_user_config_directory(path: Path) -> None:
    if path.is_symlink():
        raise SyncError(f"用户级默认目录不能是 symlink：{path}")
    if path.exists() and not path.is_dir():
        raise SyncError(f"用户级默认目录必须是目录：{path}")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o700:
        path_stat = path.stat()
        owned_by_user = not hasattr(os, "getuid") or path_stat.st_uid == os.getuid()
        if not owned_by_user or not os.access(path, os.W_OK):
            raise SyncError(f"用户级默认目录权限必须是 0700，且当前用户无法修正：{path}")
        path.chmod(0o700)


def write_new_text_file(path: Path, content: str, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    except FileExistsError as exc:
        raise SyncError(f"目标文件已存在，拒绝覆盖：{path}") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(content)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    path.chmod(mode)


def merge_dotenv_values(path: Path, desired: dict[str, str], *, private: bool) -> list[str]:
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise SyncError(f"dotenv 目标必须是普通文件且不能是 symlink：{path}")
        if private:
            secure_external_plaintext_file(path, "env_file")
        raw = path.read_text(encoding="utf-8")
        current = parse_env_file(path)
        lines = raw.splitlines()
    else:
        raw = ""
        current = {}
        lines = []

    changed: list[str] = []
    replacements = {key: value for key, value in desired.items() if key in current and not current[key] and value}
    if replacements:
        for index, raw_line in enumerate(lines):
            candidate = raw_line.strip()
            if candidate.startswith("export "):
                candidate = candidate[7:].lstrip()
            key = candidate.partition("=")[0].strip() if "=" in candidate else ""
            if key in replacements:
                lines[index] = f"{key}={replacements[key]}"
                current[key] = replacements[key]
                changed.append(key)

    for key, value in desired.items():
        if key not in current:
            lines.append(f"{key}={value}")
            current[key] = value
            changed.append(key)

    if not path.exists():
        content = "\n".join(lines) + ("\n" if lines else "")
        write_new_text_file(path, content, mode=0o600 if private else 0o644)
    elif changed:
        content = "\n".join(lines) + ("\n" if lines or raw.endswith("\n") else "")
        path.write_text(content, encoding="utf-8")
        if private:
            path.chmod(0o600)
    return changed


def ensure_user_defaults(path: Path | None = None) -> tuple[Path, dict[str, str]]:
    defaults_path = path or user_defaults_file()
    ensure_user_config_directory(defaults_path.parent)
    current: dict[str, str] = {}
    if defaults_path.exists():
        current = parse_env_file(secure_external_plaintext_file(defaults_path, "用户级 defaults"))
    credential = current.get("ADMIN_PASSWORD") or current.get("OPS_TOKEN") or generated_default_value()
    desired = {
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": credential,
        "OPS_TOKEN": credential,
    }
    merge_dotenv_values(defaults_path, desired, private=True)
    values = parse_env_file(secure_external_plaintext_file(defaults_path, "用户级 defaults"))
    missing = [key for key in STANDARD_KEYS if not values.get(key)]
    if missing:
        raise SyncError(f"用户级 defaults 缺少可用值：{missing}")
    return defaults_path, values


def default_project_slug(root: Path) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", root.name).strip("-._")
    if not slug or not slug[0].isalnum():
        return "my-app"
    return slug[:96]


def render_template(name: str, *, project: str | None = None) -> str:
    path = TEMPLATE_DIR / name
    if not path.is_file():
        raise SyncError(f"缺少 hfs-dev 模板：{path}")
    content = path.read_text(encoding="utf-8")
    return content.replace("__PROJECT__", project or "my-app")


def cmd_init(
    root: Path,
    manifest_file: Path = Path("hfs-dev.toml"),
    *,
    defaults_file: Path | None = None,
) -> int:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise SyncError(f"项目根必须是目录：{root}")

    manifest_path = resolve_local_file(root, manifest_file, "manifest")
    manifest: dict[str, Any] | None = None
    if manifest_path.exists():
        # 先验后写：旧标准或非法 manifest 在任何文件改动前失败
        manifest = load_manifest(root, manifest_file)
        validate_manifest(manifest)

    selected_env_file = manifest_env_file(manifest) if manifest is not None else Path(".env")
    project_env_path = resolve_local_file(root, selected_env_file, "env_file")

    defaults_path, defaults = ensure_user_defaults(defaults_file)
    env_values = {
        "ADMIN_USERNAME": defaults["ADMIN_USERNAME"],
        "ADMIN_PASSWORD": defaults["ADMIN_PASSWORD"],
        "OPS_TOKEN": defaults["OPS_TOKEN"],
        "HF_TOKEN": "",
        "GH_TOKEN": "",
    }
    changed_env = merge_dotenv_values(project_env_path, env_values, private=True)

    created: list[Path] = []
    example_path = root / ".env.example"
    if example_path.exists():
        merge_dotenv_values(
            example_path,
            {
                "ADMIN_USERNAME": "admin",
                "ADMIN_PASSWORD": "",
                "OPS_TOKEN": "",
                "HF_TOKEN": "",
                "GH_TOKEN": "",
            },
            private=False,
        )
    else:
        write_new_text_file(example_path, render_template("env.example"), mode=0o644)
        created.append(Path(".env.example"))

    for relative, template in ((Path("config.toml"), "config.toml"),):
        target = root / relative
        if not target.exists():
            write_new_text_file(target, render_template(template), mode=0o644)
            created.append(relative)

    if not manifest_path.exists():
        write_new_text_file(
            manifest_path,
            render_template("hfs-dev.toml", project=default_project_slug(root)),
            mode=0o644,
        )
        created.append(manifest_path.relative_to(root))

    print("HFS 项目初始化完成。")
    print(f"用户级默认：{defaults_path}")
    if created:
        print(f"已创建：{', '.join(str(path) for path in created)}")
    if changed_env:
        print(f"{selected_env_file} 已补全：{', '.join(changed_env)}")
    else:
        print(f"{selected_env_file} 已完整，未覆盖现有值")
    project_env = parse_env_file(project_env_path)
    print(f"管理员用户名：{project_env['ADMIN_USERNAME']}")
    print(f"管理员密码：{project_env['ADMIN_PASSWORD']}")
    print(f"OPS token：{project_env['OPS_TOKEN']}")
    print("下一步：运行 hfs-dev check 校验对齐；hfs-dev info 查看项目信息（不显示值）")
    return 0


def application_url(space: str) -> str | None:
    """HFS 默认 subdomain 为 {owner}-{slug}；slug-only 时离线无法确定，返回 None。"""
    parts = space.split("/")
    if len(parts) != 2 or not all(parts):
        return None
    owner, slug = parts
    host = re.sub(r"[^a-z0-9-]+", "-", f"{owner}-{slug}".lower().replace("_", "-")).strip("-")
    if not host:
        return None
    return f"https://{host}.hf.space"


def cmd_info(
    root: Path,
    manifest_file: Path = Path("hfs-dev.toml"),
    env_file: Path | None = None,
    *,
    names_only: bool = False,
    debug: bool = False,
) -> int:
    root = root.resolve()
    manifest = load_manifest(root, manifest_file)
    validate_manifest(manifest)
    selected_env_file = manifest_env_file(manifest, env_file)
    env_values = load_env(root, selected_env_file)
    missing = [key for key in STANDARD_KEYS if not env_values.get(key)]
    if missing:
        keys = "、".join(missing)
        raise SyncError(
            f"{selected_env_file} 缺少可用标准键：{keys}。\n"
            "请运行 hfs-dev init，或在该文件中补充对应 KEY=VALUE。"
        )

    app_url = application_url(str(manifest["space"]))
    print("Project")
    print(f"  name: {manifest['project']}")
    print(f"  class: {manifest['project_class']}")
    print(f"  space: {manifest['space']}")
    print("\nApplication")
    if app_url is None:
        print("  URL: 离线无法确定（space 未包含 owner；以 Space 页面为准）")
    else:
        print(f"  URL: {app_url}")
        print(f"  Admin URL: {app_url}/admin")
    print("\nLogin")
    print("  ADMIN_USERNAME: 已设置" if env_values.get("ADMIN_USERNAME") else "  ADMIN_USERNAME: 未设置")
    print("  ADMIN_PASSWORD: 已设置" if env_values.get("ADMIN_PASSWORD") else "  ADMIN_PASSWORD: 未设置")
    print("\nOperations")
    print("  OPS_TOKEN: 已设置" if env_values.get("OPS_TOKEN") else "  OPS_TOKEN: 未设置")
    print(f"  info 永不显示值；需要实际值时查看 {selected_env_file}")
    secrets, optional_secrets, variables = registered_names(manifest)
    if secrets or optional_secrets or variables:
        print("\nRegistered")
        for name in sorted(secrets):
            print(f"  secret {name}: {'已设置' if env_values.get(name) else '未设置'}")
        for name in sorted(optional_secrets):
            print(f"  optional secret {name}: {'已设置' if env_values.get(name) else '未设置'}")
        for name in sorted(variables):
            print(f"  variable {name}: {'已设置' if env_values.get(name) else '未设置'}")
    print("\nPrecedence")
    print("  进程环境变量 > 项目 .env > config.toml > 程序内置默认值")
    print("\nSources")
    print(f"  值事实源: {selected_env_file}")
    print("  非机密配置: config.toml")
    print("  部署声明: hfs-dev.toml")
    print("  wrapper 生成物: local/generated/（从标准 .env 生成，不作权威源）")
    if debug:
        mapping = env_map(manifest)
        print("\nEnvironment map")
        if mapping:
            for source, target in sorted(mapping.items()):
                print(f"  {source} -> {target}")
        else:
            print("  none")
    return 0


_CHECKER_MODULE: Any | None = None


def load_checker_module() -> Any:
    global _CHECKER_MODULE
    if _CHECKER_MODULE is None:
        checker_path = Path(__file__).resolve().parent / "check_hfs_alignment.py"
        spec = importlib.util.spec_from_file_location("check_hfs_alignment", checker_path)
        if spec is None or spec.loader is None:
            raise SyncError(f"无法加载检查器：{checker_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _CHECKER_MODULE = module
    return _CHECKER_MODULE


def cmd_check(root: Path, manifest_file: Path | None = None) -> int:
    root = root.resolve()
    if not root.is_dir():
        raise SyncError(f"项目根不存在：{root}")
    checker = load_checker_module()
    return int(checker.check_root(root, manifest_file=manifest_file))


def load_env(root: Path, env_file: Path = Path(".env")) -> dict[str, str]:
    path = secure_plaintext_file(root, env_file, "env_file")
    return parse_env_file(path)


def string_list(manifest: dict[str, Any], field: str) -> list[str]:
    value = manifest.get(field, [])
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise SyncError(f"hfs-dev manifest 的 {field} 必须是非空字符串组成的数组")
    if len(value) != len(set(value)):
        raise SyncError(f"hfs-dev manifest 的 {field} 存在重复项")
    return value


def validate_slug(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SAFE_SLUG.fullmatch(value):
        raise SyncError(f"{field} 必须是安全的单段名称：{value!r}")
    return value


def validate_space_id(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise SyncError("space 必须是非空字符串")
    if not SPACE_ID.fullmatch(value):
        raise SyncError(f"space ID 非法：{value!r}")
    if "--" in value or ".." in value or value.endswith(".git"):
        raise SyncError(f"space ID 非法：{value!r}")
    return value


def validate_object_path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise SyncError(f"{field} 必须是非空相对路径")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise SyncError(f"{field} 不能是绝对路径或包含 . / ..：{value!r}")
    return str(path)


def validate_setting_names(names: set[str], field: str) -> None:
    invalid = sorted(name for name in names if not ENV_KEY.fullmatch(name))
    if invalid:
        raise SyncError(f"{field} 包含非法环境变量键名：{invalid}")


def validate_manifest(manifest: dict[str, Any]) -> None:
    standard = str(manifest.get("standard", ""))
    if standard in LEGACY_STANDARDS:
        raise SyncError(
            f"standard {standard!r} 已不再受支持；v3.0 正常运行只接受 standard = \"3.0\"。\n"
            "请运行 hfs-dev check 查看迁移差距报告，并按 README「从 2.1/2.2 迁移」配方人工迁移。"
        )
    if standard not in SUPPORTED_STANDARDS:
        supported = "、".join(sorted(SUPPORTED_STANDARDS))
        raise SyncError(f"standard 必须是受支持版本：{supported}")
    validate_slug(manifest.get("project"), "project")

    validate_space_id(manifest.get("space"))

    sovereignty = manifest.get("sovereignty")
    if not isinstance(sovereignty, str) or sovereignty not in SOVEREIGNTIES:
        raise SyncError("sovereignty 必须是 sovereign、fork 或 port")
    lane = manifest.get("lane")
    if not isinstance(lane, str) or lane not in LANES:
        raise SyncError("lane 必须是 source 或 artifact")
    version_source = manifest.get("version_source")
    if not isinstance(version_source, str) or version_source not in VERSION_SOURCES:
        raise SyncError("version_source 必须是 latest、tag 或 commit")
    project_class = manifest.get("project_class")
    if not isinstance(project_class, str) or project_class not in PROJECT_CLASSES:
        raise SyncError("project_class 必须是 preview 或 production")
    target_role = manifest.get("target_role")
    if not isinstance(target_role, str) or target_role not in TARGET_ROLES:
        raise SyncError("target_role 必须是 primary、rotation、candidate 或 restore")
    space_visibility = manifest.get("space_visibility")
    if not isinstance(space_visibility, str) or space_visibility not in SPACE_VISIBILITIES:
        raise SyncError("space_visibility 必须是 protected")
    bucket_visibility = manifest.get("bucket_visibility")
    if not isinstance(bucket_visibility, str) or bucket_visibility not in BUCKET_VISIBILITIES:
        raise SyncError("bucket_visibility 必须是 private")
    validate_env_file_path(manifest.get("env_file"))
    if "secret_files" in manifest:
        raise SyncError(
            "secret_files 已在 v3.0 移除：机密只登记在 .env；"
            "确需原生结构化文件时，由 wrapper 从标准 .env 生成到 local/generated/"
        )
    if "env_map" in manifest:
        raise SyncError(
            "env_map 已移动到 [compat.env_map]；sovereign 项目禁止使用映射"
        )
    unknown_fields = sorted(set(manifest) - MANIFEST_ROOT_FIELDS)
    if unknown_fields:
        raise SyncError(f"hfs-dev manifest 含未知根字段：{unknown_fields}")

    if "bucket_namespace" in manifest:
        validate_slug(manifest["bucket_namespace"], "bucket_namespace")
    validate_slug(manifest.get("dist_bucket", DEFAULT_DIST_BUCKET), "dist_bucket")
    if "mount_config_bucket" in manifest and manifest["mount_config_bucket"] not in (None, ""):
        validate_slug(manifest["mount_config_bucket"], "mount_config_bucket")
        validate_object_path(manifest.get("mount_config_object", "config/config.toml"), "mount_config_object")

    secrets = set(string_list(manifest, "secrets"))
    optional_secrets = set(string_list(manifest, "optional_secrets"))
    variables = set(string_list(manifest, "variables"))
    local_only = DEFAULT_LOCAL_ONLY | set(string_list(manifest, "local_only"))
    validate_setting_names(secrets, "secrets")
    validate_setting_names(optional_secrets, "optional_secrets")
    validate_setting_names(variables, "variables")
    validate_setting_names(local_only, "local_only")
    if secrets & optional_secrets:
        raise SyncError(
            "同一键不能同时登记为 required secret 和 optional secret："
            f"{sorted(secrets & optional_secrets)}"
        )
    secret_variable_overlap = (secrets | optional_secrets) & variables
    if secret_variable_overlap:
        raise SyncError(
            "同一键不能同时登记为 secret/optional secret 和 variable："
            f"{sorted(secret_variable_overlap)}"
        )
    local_overlap = (secrets | optional_secrets | variables) & local_only
    if local_overlap:
        raise SyncError(
            "本地控制凭据不能登记为 Space secret/optional secret/variable："
            f"{sorted(local_overlap)}"
        )
    forbidden = [
        f"{name}（{forbidden_key_reason(name)}）"
        for name in sorted(secrets | optional_secrets | variables)
        if forbidden_key_reason(name)
    ]
    if forbidden:
        raise SyncError(f"v3.0 禁止登记的旧式键名：{'、'.join(forbidden)}")
    validate_compat(manifest, secrets | optional_secrets | variables, sovereignty)

    seed_value = manifest.get("seed_file")
    other_objects = string_list(manifest, "other_objects")
    if seed_value not in (None, ""):
        seed_relative = validate_object_path(seed_value, "seed_file")
        if Path(seed_relative).name not in other_objects:
            raise SyncError("seed_file 的文件名必须登记在 other_objects")
    for item in other_objects:
        validate_object_path(item, "other_objects")


def local_only_names(manifest: dict[str, Any]) -> set[str]:
    return DEFAULT_LOCAL_ONLY | set(string_list(manifest, "local_only"))


def registered_names(manifest: dict[str, Any]) -> tuple[set[str], set[str], set[str]]:
    secrets = set(string_list(manifest, "secrets"))
    optional_secrets = set(string_list(manifest, "optional_secrets"))
    variables = set(string_list(manifest, "variables"))
    return secrets, optional_secrets, variables


def env_map(manifest: dict[str, Any]) -> dict[str, str]:
    compat = manifest.get("compat", {})
    if not isinstance(compat, dict):
        raise SyncError("hfs-dev manifest 的 [compat] 必须是 table")
    value = compat.get("env_map", {})
    if not isinstance(value, dict) or not all(
        isinstance(source, str) and isinstance(target, str) and target
        for source, target in value.items()
    ):
        raise SyncError("hfs-dev manifest 的 [compat.env_map] 必须是标准键到上游键的字符串映射")
    return dict(value)


def validate_compat(manifest: dict[str, Any], registered: set[str], sovereignty: str) -> None:
    compat = manifest.get("compat", {})
    if not isinstance(compat, dict):
        raise SyncError("hfs-dev manifest 的 [compat] 必须是 table")
    unknown_sections = sorted(set(compat) - {"env_map", "expires_after"})
    if unknown_sections:
        raise SyncError(f"[compat] 只允许 env_map 和 expires_after：{unknown_sections}")
    expires = compat.get("expires_after")
    if expires is not None and (not isinstance(expires, str) or not expires.strip()):
        raise SyncError("[compat] expires_after 必须是非空字符串")
    mapping = env_map(manifest)
    validate_setting_names(set(mapping), "[compat.env_map] 源键")
    validate_setting_names(set(mapping.values()), "[compat.env_map] 目标键")
    unknown = sorted(set(mapping) - registered)
    if unknown:
        raise SyncError(f"[compat.env_map] 只能映射已登记的 Secret/Variable 键：{unknown}")
    targets: dict[str, str] = {}
    for source in sorted(registered):
        target = mapping.get(source, source)
        previous = targets.get(target)
        if previous is not None and previous != source:
            raise SyncError(f"[compat.env_map] 目标键重复：{previous}、{source} -> {target}")
        targets[target] = source
    if mapping and sovereignty == "sovereign":
        raise SyncError(
            "sovereign 项目禁止使用 [compat.env_map]；只有 fork/port 可在过渡期内映射上游键"
        )


def remote_setting_name(manifest: dict[str, Any], local_name: str) -> str:
    return env_map(manifest).get(local_name, local_name)


def remote_setting_names(manifest: dict[str, Any], local_names: set[str]) -> set[str]:
    return {remote_setting_name(manifest, name) for name in local_names}


def manifest_env_file(manifest: dict[str, Any], override: Path | None = None) -> Path:
    declared = Path(validate_env_file_path(manifest.get("env_file")))
    if override is not None and override != declared:
        raise SyncError(
            f"--env-file 必须与 manifest 的 env_file 一致：声明 {declared}，收到 {override}"
        )
    return declared


def env_key_names(path: Path) -> set[str]:
    names: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key = line.partition("=")[0].strip()
        if ENV_KEY.fullmatch(key):
            names.add(key)
    return names


def declared_profile_env_files(root: Path) -> set[Path]:
    declared: set[Path] = set()
    for manifest_path in root.glob("hfs-dev*.toml"):
        try:
            with manifest_path.open("rb") as file:
                manifest = tomllib.load(file)
            relative = Path(validate_env_file_path(manifest.get("env_file")))
            declared.add(resolve_local_file(root, relative, "env_file"))
        except (OSError, SyncError, tomllib.TOMLDecodeError):
            continue
    return declared


def conflicting_env_sources(
    root: Path,
    declared: Path,
    registered: set[str],
) -> list[str]:
    candidates = list(root.glob(".env*")) + list((root / "local" / "hfs-targets").glob("*.env"))
    conflicts: list[str] = []
    declared_path = resolve_local_file(root, declared, "env_file")
    profile_paths = declared_profile_env_files(root)
    for candidate in candidates:
        if candidate.name.endswith((".example", ".sample", ".template")):
            continue
        if candidate.resolve() == declared_path or candidate.resolve() in profile_paths or not candidate.is_file():
            continue
        if env_key_names(candidate) & registered:
            conflicts.append(str(candidate.relative_to(root)))
    return sorted(set(conflicts))


def hf_token(env_values: dict[str, str]) -> str:
    token = env_values.get("HF_TOKEN", "").strip()
    if not token:
        raise SyncError("env 文件缺少 HF_TOKEN；脚本不会隐式改用机器上的其他账号")
    return token


def api_client(token: str) -> HfApi:
    from huggingface_hub import HfApi

    return HfApi(token=token)


def token_namespace(api: HfApi, token: str) -> str:
    name = api.whoami(token=token).get("name")
    if not isinstance(name, str) or not name:
        raise SyncError("HF_TOKEN 无法解析当前账号")
    return name


def space_id(manifest: dict[str, Any], token_owner: str) -> str:
    slug = manifest["space"].strip()
    return slug if "/" in slug else f"{token_owner}/{slug}"


def bucket_namespace(manifest: dict[str, Any], resolved_space: str) -> str:
    explicit = manifest.get("bucket_namespace")
    return explicit if isinstance(explicit, str) and explicit else resolved_space.split("/", 1)[0]


def seed_path(root: Path, manifest: dict[str, Any]) -> Path | None:
    value = manifest.get("seed_file")
    if value in (None, ""):
        return None
    return resolve_local_file(root, Path(value), "seed_file")


def seed_uri(storage_owner: str, manifest: dict[str, Any], local_seed: Path) -> str:
    bucket = manifest.get("dist_bucket", DEFAULT_DIST_BUCKET)
    project = manifest["project"]
    return f"hf://buckets/{storage_owner}/{bucket}/{project}/other/{local_seed.name}"


def instance_uri(manifest: dict[str, Any], storage_owner: str) -> str | None:
    bucket = manifest.get("mount_config_bucket")
    if bucket in (None, ""):
        return None
    object_name = manifest.get("mount_config_object", "config/config.toml")
    return f"hf://buckets/{storage_owner}/{bucket}/{str(object_name).lstrip('/')}"


def registered_bucket_ids(manifest: dict[str, Any], storage_owner: str) -> list[str]:
    names: set[str] = set()
    if (
        "dist_bucket" in manifest
        or manifest.get("lane") == "artifact"
        or manifest.get("seed_file") not in (None, "")
    ):
        names.add(str(manifest.get("dist_bucket", DEFAULT_DIST_BUCKET)))
    mount_bucket = manifest.get("mount_config_bucket")
    if isinstance(mount_bucket, str) and mount_bucket:
        names.add(mount_bucket)
    return [f"{storage_owner}/{name}" for name in sorted(names)]


def space_visibility(api: HfApi, space: str, token: str) -> str:
    namespace = space.split("/", 1)[0]
    token_owner = token_namespace(api, token)
    kwargs: dict[str, Any] = {"token": token}
    if namespace.casefold() != token_owner.casefold():
        kwargs["namespace"] = namespace
    try:
        repos = api.list_user_repos(**kwargs)
        match = next(
            (
                repo
                for repo in repos
                if getattr(repo, "id", None) == space and getattr(repo, "type", None) == "space"
            ),
            None,
        )
    except Exception as exc:
        raise SyncError(f"Space visibility 读取失败：{space}") from exc
    visibility = getattr(match, "visibility", None)
    if not isinstance(visibility, str) or not visibility:
        raise SyncError(f"Space visibility 读回缺失：{space}")
    return visibility


def bucket_is_private(api: HfApi, bucket_id: str, token: str) -> bool:
    try:
        info = api.bucket_info(bucket_id, token=token)
    except Exception as exc:
        raise SyncError(f"bucket visibility 读取失败：{bucket_id}") from exc
    private = getattr(info, "private", None)
    if not isinstance(private, bool):
        raise SyncError(f"bucket visibility 读回缺失：{bucket_id}")
    return private


def visibility_drift(
    api: HfApi,
    manifest: dict[str, Any],
    space: str,
    storage_owner: str,
    token: str,
) -> list[str]:
    findings: list[str] = []
    actual_space_visibility = space_visibility(api, space, token)
    expected_space_visibility = manifest["space_visibility"]
    if actual_space_visibility != expected_space_visibility:
        findings.append(
            f"Space {space}: {actual_space_visibility} != {expected_space_visibility}"
        )
    expected_bucket_visibility = manifest["bucket_visibility"]
    for bucket_id in registered_bucket_ids(manifest, storage_owner):
        actual_bucket_visibility = "private" if bucket_is_private(api, bucket_id, token) else "public"
        if actual_bucket_visibility != expected_bucket_visibility:
            findings.append(
                f"bucket {bucket_id}: {actual_bucket_visibility} != {expected_bucket_visibility}"
            )
    return findings


def reconcile_visibility(
    api: HfApi,
    manifest: dict[str, Any],
    space: str,
    storage_owner: str,
    token: str,
) -> None:
    expected_bucket_visibility = manifest["bucket_visibility"]
    bucket_findings = []
    for bucket_id in registered_bucket_ids(manifest, storage_owner):
        actual = "private" if bucket_is_private(api, bucket_id, token) else "public"
        if actual != expected_bucket_visibility:
            bucket_findings.append(f"{bucket_id}={actual}")
    if bucket_findings:
        raise SyncError(
            "bucket 必须先手工调整为 private，未执行任何 Space 写入："
            f"{bucket_findings}"
        )

    expected_space_visibility = manifest["space_visibility"]
    if space_visibility(api, space, token) != expected_space_visibility:
        api.update_repo_settings(
            space,
            repo_type="space",
            visibility=expected_space_visibility,
            token=token,
        )
        if space_visibility(api, space, token) != expected_space_visibility:
            raise SyncError(
                f"Space visibility 读回失败：{space} 未稳定为 {expected_space_visibility}"
            )
        print(f"Space visibility 已调整并读回：{expected_space_visibility}")
    else:
        print(f"Space visibility 已符合：{expected_space_visibility}")
    print(f"bucket visibility 读回通过：{expected_bucket_visibility}")


def space_secret_names(space: str, token: str) -> set[str]:
    from huggingface_hub.utils import build_hf_headers

    request = urllib.request.Request(
        f"https://huggingface.co/api/spaces/{space}/secrets",
        headers=build_hf_headers(token=token),
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    if not isinstance(data, dict):
        raise SyncError("HF Secret 名单接口返回了无法识别的数据")
    return set(data)


def bucket_cp(source: str, destination: str, token: str) -> tuple[bool, str]:
    process_env = os.environ.copy()
    process_env["HF_TOKEN"] = token
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "huggingface_hub.cli.hf",
            "buckets",
            "cp",
            source,
            destination,
            "--quiet",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=process_env,
    )
    message = (result.stderr or result.stdout).strip().splitlines()
    return result.returncode == 0, message[-1] if message else ""


def bucket_read_bytes(source: str, token: str) -> tuple[bool, bytes]:
    process_env = os.environ.copy()
    process_env["HF_TOKEN"] = token
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "huggingface_hub.cli.hf",
            "buckets",
            "cp",
            source,
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=process_env,
    )
    return result.returncode == 0, result.stdout


def normalized_sensitive_key(key: str) -> bool:
    with_boundaries = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    normalized = with_boundaries.lower().replace("-", "_").replace(".", "_")
    return any(normalized == term or normalized.endswith(f"_{term}") for term in SENSITIVE_KEY_SUFFIXES)


def placeholder_value(value: Any) -> bool:
    if value is None or value is False:
        return True
    if not isinstance(value, str):
        return False
    stripped = value.strip().strip('"').strip("'")
    if not stripped or stripped.upper() in SAFE_PLACEHOLDERS:
        return True
    if re.fullmatch(r"\$\{[A-Za-z_][A-Za-z0-9_]*(?::-[^}]*)?\}", stripped):
        return True
    if re.fullmatch(r"env:[A-Za-z_][A-Za-z0-9_]*", stripped):
        return True
    if ANGLE_PLACEHOLDER.fullmatch(stripped):
        return True
    return False


def embedded_credential(value: str) -> bool:
    for candidate in URL_VALUE.findall(value):
        candidate = candidate.rstrip(",);]")
        try:
            parsed = urllib.parse.urlsplit(candidate)
            password = parsed.password
        except ValueError:
            parsed = None
            password = None
        if password is not None and not placeholder_value(urllib.parse.unquote(password)):
            return True
        if parsed is not None:
            for key, query_value in urllib.parse.parse_qsl(
                parsed.query,
                keep_blank_values=True,
            ):
                if normalized_sensitive_key(key) and not placeholder_value(query_value):
                    return True
    for match in DSN_FIELD.finditer(value):
        if normalized_sensitive_key(match.group("key")) and not placeholder_value(
            match.group("value")
        ):
            return True
    return False


def matching_protected_names(
    value: str,
    protected_values: dict[str, tuple[str, str]],
) -> list[tuple[str, str]]:
    matches: list[tuple[str, str]] = []
    for name, (category, secret) in protected_values.items():
        if value == secret or (len(secret) >= 8 and secret in value):
            matches.append((category, name))
    return matches


def scalar_sensitive_fields(
    value: Any,
    location: str,
    protected_values: dict[str, tuple[str, str]],
) -> list[str]:
    if not isinstance(value, str):
        return []
    findings: list[str] = []
    if embedded_credential(value):
        findings.append(f"{location}:embedded-credential")
    for category, name in matching_protected_names(value, protected_values):
        findings.append(f"{location}:{category}:{name}")
    return findings


def structured_sensitive_fields(
    value: Any,
    protected_values: dict[str, tuple[str, str]],
    prefix: str = "",
) -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if normalized_sensitive_key(key_text) and not placeholder_value(child):
                findings.append(path)
            findings.extend(scalar_sensitive_fields(child, path, protected_values))
            findings.extend(structured_sensitive_fields(child, protected_values, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            path = f"{prefix}[{index}]"
            findings.extend(scalar_sensitive_fields(child, path, protected_values))
            findings.extend(structured_sensitive_fields(child, protected_values, path))
    else:
        findings.extend(scalar_sensitive_fields(value, prefix or "<root>", protected_values))
    return findings


def deduplicated(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def strip_unquoted_comment(line: str) -> str:
    quote: str | None = None
    escaped = False
    for index, character in enumerate(line):
        if escaped:
            escaped = False
            continue
        if character == "\\" and quote is not None:
            escaped = True
            continue
        if character in {'"', "'"}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
            continue
        if character == "#" and quote is None:
            return line[:index]
    return line


def sensitive_seed_text(
    raw: str,
    suffix: str,
    protected_values: dict[str, tuple[str, str]] | None = None,
    *,
    strict_format: bool = False,
) -> list[str]:
    protected_values = protected_values or {}
    suffix = suffix.lower()
    literal_findings = ["literal-token-pattern"] if LITERAL_SECRET.search(raw) else []
    if suffix == ".toml":
        try:
            parsed = tomllib.loads(raw)
        except tomllib.TOMLDecodeError:
            raise SyncError("种子 TOML 解析失败（不输出配置原文）") from None
        return deduplicated(literal_findings + structured_sensitive_fields(parsed, protected_values))
    if suffix == ".json":
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SyncError(f"种子 JSON 解析失败：第 {exc.lineno} 行第 {exc.colno} 列") from None
        return deduplicated(literal_findings + structured_sensitive_fields(parsed, protected_values))
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:
            raise SyncError("YAML seed 解析需要安装 PyYAML>=6.0") from exc
        try:
            documents = list(yaml.safe_load_all(raw))
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            if mark is not None and isinstance(mark.line, int) and isinstance(mark.column, int):
                location = f"第 {mark.line + 1} 行第 {mark.column + 1} 列"
            else:
                location = "位置未知"
            raise SyncError(f"种子 YAML 解析失败：{location}（不输出配置原文）") from None
        findings = list(literal_findings)
        for index, document in enumerate(documents):
            findings.extend(structured_sensitive_fields(document, protected_values, f"document[{index}]"))
        return deduplicated(findings)

    if strict_format and suffix not in TEXT_SEED_SUFFIXES:
        supported = ", ".join(sorted(item or "无扩展名" for item in STRUCTURED_SEED_SUFFIXES | TEXT_SEED_SUFFIXES))
        raise SyncError(
            f"种子格式 {suffix or '无扩展名'} 无法可靠检查；"
            f"示例脚本仅允许 {supported}，请为上游格式提供项目级安全扫描后再同步"
        )

    findings: list[str] = list(literal_findings)
    for number, raw_line in enumerate(raw.splitlines(), start=1):
        findings.extend(
            scalar_sensitive_fields(raw_line, f"line:{number}", protected_values)
        )
        line = strip_unquoted_comment(raw_line).rstrip()
        match = TEXT_KEY_VALUE.match(line)
        if match:
            location = f"line:{number}:{match.group(1)}"
            if normalized_sensitive_key(match.group(1)) and not placeholder_value(match.group(2)):
                findings.append(location)
            findings.extend(scalar_sensitive_fields(match.group(2), location, protected_values))
        else:
            findings.extend(scalar_sensitive_fields(line, f"line:{number}", protected_values))
    return deduplicated(findings)


def sensitive_seed_fields(
    path: Path,
    protected_values: dict[str, tuple[str, str]] | None = None,
    *,
    strict_format: bool = False,
) -> list[str]:
    return sensitive_seed_text(
        path.read_text(encoding="utf-8", errors="replace"),
        path.suffix,
        protected_values,
        strict_format=strict_format,
    )


def configured_optional_secrets(
    env_values: dict[str, str], optional_secrets: set[str]
) -> set[str]:
    return {name for name in optional_secrets if env_values.get(name, "")}


def protected_secret_values(
    env_values: dict[str, str], manifest: dict[str, Any]
) -> dict[str, tuple[str, str]]:
    secrets, optional_secrets, _ = registered_names(manifest)
    protected: dict[str, tuple[str, str]] = {}
    for name in secrets | optional_secrets:
        if env_values.get(name) and not placeholder_value(env_values[name]):
            protected[name] = ("env-secret", env_values[name])
    for name in local_only_names(manifest):
        if env_values.get(name) and not placeholder_value(env_values[name]):
            protected[name] = ("local-only", env_values[name])
    return protected


def unsafe_variable_reasons(
    name: str,
    value: str,
    protected_values: dict[str, tuple[str, str]],
) -> list[str]:
    reasons: list[str] = []
    if embedded_credential(value):
        reasons.append(f"{name}:embedded-credential")
    if LITERAL_SECRET.search(value):
        reasons.append(f"{name}:literal-token-pattern")
    for category, protected_name in matching_protected_names(value, protected_values):
        reasons.append(f"{name}:{category}:{protected_name}")
    return reasons


def unsafe_local_only_aliases(
    env_values: dict[str, str],
    manifest: dict[str, Any],
    setting_names: set[str],
) -> list[str]:
    protected_values = {
        name: ("local-only", env_values[name])
        for name in local_only_names(manifest)
        if env_values.get(name) and not placeholder_value(env_values[name])
    }
    findings: list[str] = []
    for name in sorted(setting_names):
        for _, protected_name in matching_protected_names(env_values[name], protected_values):
            findings.append(f"{name}:local-only:{protected_name}")
    return findings


def report(title: str, items: list[str]) -> int:
    print(f"[{title}] {len(items)} 项" if items else f"[{title}] 无差异")
    for item in items:
        print(f"  - {item}")
    return len(items)


def preflight(
    root: Path,
    manifest_file: Path = Path("hfs-dev.toml"),
    env_file: Path | None = None,
    *,
    for_push: bool = False,
) -> tuple[
    dict[str, Any],
    dict[str, str],
    str,
    set[str],
    set[str],
    set[str],
    Path | None,
]:
    root = root.resolve()
    manifest = load_manifest(root, manifest_file)
    validate_manifest(manifest)
    selected_env_file = manifest_env_file(manifest, env_file)
    env_values = load_env(root, selected_env_file)
    token = hf_token(env_values)
    secrets, optional_secrets, variables = registered_names(manifest)
    missing = sorted(name for name in secrets | variables if not env_values.get(name, ""))
    if missing:
        raise SyncError(f"env 文件缺少已登记值，未执行任何写操作：{missing}")
    present_optional_secrets = configured_optional_secrets(env_values, optional_secrets)
    placeholder_settings = sorted(
        name
        for name in secrets | variables | present_optional_secrets
        if placeholder_value(env_values[name])
    )
    if placeholder_settings:
        raise SyncError(
            f"env 文件中的 Secret/Variable 仍是占位符，未执行任何写操作：{placeholder_settings}"
        )
    duplicate_sources = conflicting_env_sources(
        root,
        selected_env_file,
        secrets | optional_secrets | variables | local_only_names(manifest),
    )
    if duplicate_sources:
        raise SyncError(f"发现包含登记键的第二 env 事实源：{duplicate_sources}")
    protected_values = protected_secret_values(env_values, manifest)
    variable_findings: list[str] = []
    for name in sorted(variables):
        variable_findings.extend(
            unsafe_variable_reasons(name, env_values[name], protected_values)
        )
    if variable_findings:
        raise SyncError(
            "Space Variable 值疑似含凭据，未执行任何写操作；"
            f"仅列出键名和原因：{deduplicated(variable_findings)}"
        )
    local_only_aliases = unsafe_local_only_aliases(
        env_values,
        manifest,
        secrets | present_optional_secrets,
    )
    if local_only_aliases:
        raise SyncError(
            "Space Secret 值与本地控制凭据重合，未执行任何写操作；"
            f"仅列出键名和来源：{local_only_aliases}"
        )
    local_seed = seed_path(root, manifest)
    if local_seed is not None and not local_seed.is_file():
        raise SyncError(f"seed_file 不存在，未执行任何写操作：{local_seed}")
    if for_push and local_seed is not None:
        sensitive = sensitive_seed_fields(
            local_seed,
            protected_values,
            strict_format=True,
        )
        if sensitive:
            raise SyncError(f"种子疑似包含实际 secret，禁止上传；字段位置：{sensitive}")
    return (
        manifest,
        env_values,
        token,
        secrets,
        optional_secrets,
        variables,
        local_seed,
    )


def resolve_targets(api: HfApi, manifest: dict[str, Any], token: str) -> tuple[str, str]:
    user = token_namespace(api, token)
    space = space_id(manifest, user)
    storage_owner = bucket_namespace(manifest, space)
    print(f"目标 Space：{space}")
    print(f"bucket namespace：{storage_owner}")
    print(f"下载 bucket：hf://buckets/{storage_owner}/{manifest.get('dist_bucket', DEFAULT_DIST_BUCKET)}")
    runtime = instance_uri(manifest, storage_owner)
    print(f"实例配置：{runtime or '未登记'}")
    return space, storage_owner


def cmd_diff(
    root: Path,
    manifest_file: Path = Path("hfs-dev.toml"),
    env_file: Path | None = None,
) -> int:
    root = root.resolve()
    (
        manifest,
        env_values,
        token,
        secrets,
        optional_secrets,
        variables,
        local_seed,
    ) = preflight(root, manifest_file, env_file)
    api = api_client(token)
    space, storage_owner = resolve_targets(api, manifest, token)
    api.space_info(space, token=token)

    differences = 0
    differences += report(
        "Space/registered bucket visibility 不一致",
        visibility_drift(api, manifest, space, storage_owner, token),
    )
    present_optional_secrets = configured_optional_secrets(env_values, optional_secrets)
    declared_secrets = remote_setting_names(manifest, secrets | optional_secrets)
    expected_secrets = remote_setting_names(manifest, secrets | present_optional_secrets)
    remote_variables_expected = remote_setting_names(manifest, variables)
    registered = secrets | optional_secrets | variables
    deployable_env = set(env_values) - local_only_names(manifest)
    differences += report("env 有但未登记", sorted(deployable_env - registered))

    remote_secrets = space_secret_names(space, token)
    remote_variables = api.get_space_variables(space, token=token)
    differences += report("远端多出 secret", sorted(remote_secrets - declared_secrets))
    differences += report(
        "远端 optional secret 缺少本地明文值",
        sorted(
            remote_setting_names(
                manifest,
                optional_secrets - present_optional_secrets,
            )
            & remote_secrets
        ),
    )
    differences += report("远端缺 secret", sorted(expected_secrets - remote_secrets))
    differences += report("远端多出 variable", sorted(set(remote_variables) - remote_variables_expected))
    differences += report("远端缺 variable", sorted(remote_variables_expected - set(remote_variables)))
    differences += report(
        "variable 值不一致",
        sorted(
            remote_setting_name(manifest, name)
            for name in variables
            if remote_setting_name(manifest, name) in remote_variables
            and remote_variables[remote_setting_name(manifest, name)].value != env_values[name]
        ),
    )

    with tempfile.TemporaryDirectory(prefix="hfs-sync-diff-") as temp_dir:
        temp = Path(temp_dir)
        seed_copy: Path | None = None
        seed_ok = False

        if local_seed is None:
            print("[种子] 未配置 seed_file，跳过")
        else:
            sensitive = sensitive_seed_fields(
                local_seed,
                protected_secret_values(env_values, manifest),
            )
            differences += report("种子含受保护值或敏感字段", sensitive)

            seed_copy = temp / f"seed-{local_seed.name}"
            seed_ok, _ = bucket_cp(
                seed_uri(storage_owner, manifest, local_seed),
                str(seed_copy),
                token,
            )
            if not seed_ok:
                print("[种子] 远端不存在或不可读")
                differences += 1
            elif seed_copy.read_bytes() == local_seed.read_bytes():
                print("[种子 vs 本地] 一致")
            else:
                print("[种子 vs 本地] 不一致（push 会更新种子）")
                differences += 1

        runtime_uri = instance_uri(manifest, storage_owner)
        if runtime_uri is None:
            print("[实例配置] 未登记 mount_config_bucket，跳过")
        else:
            instance_name = PurePosixPath(
                str(manifest.get("mount_config_object", "config/config.toml"))
            ).name
            instance_copy = temp / f"instance-{instance_name}"
            instance_ok, _ = bucket_cp(runtime_uri, str(instance_copy), token)
            if not instance_ok:
                print("[实例配置] 挂载位置不存在或不可读")
                differences += 1
            elif local_seed is None:
                print("[实例配置] 存在且可读（未配置 seed_file，跳过与种子比较）")
            elif not seed_ok or seed_copy is None:
                print("[实例 vs 种子] 未比较：远端种子不可读")
            elif instance_copy.read_bytes() == seed_copy.read_bytes():
                print("[实例 vs 种子] 一致")
            else:
                print("[实例 vs 种子] 不一致：refresh 前先 pull 到 local/，检查后再决定")
                differences += 1

    return 1 if differences else 0


def verify_seed_round_trip(local_seed: Path, remote_uri: str, token: str) -> None:
    with tempfile.TemporaryDirectory(prefix="hfs-sync-seed-readback-") as temp_dir:
        downloaded = Path(temp_dir) / local_seed.name
        success, _ = bucket_cp(remote_uri, str(downloaded), token)
        if not success:
            raise SyncError(f"种子读回失败：{remote_uri}")
        if downloaded.read_bytes() != local_seed.read_bytes():
            raise SyncError("种子读回内容与本地不一致")


def cmd_push(
    root: Path,
    prune: bool,
    yes: bool,
    manifest_file: Path = Path("hfs-dev.toml"),
    env_file: Path | None = None,
    production_confirmed: bool = False,
) -> int:
    root = root.resolve()
    if prune and not yes:
        raise SyncError("--prune 会删除远端设置，必须同时传 --yes")
    (
        manifest,
        env_values,
        token,
        secrets,
        optional_secrets,
        variables,
        local_seed,
    ) = preflight(root, manifest_file, env_file, for_push=True)
    if manifest["project_class"] == "production" and not production_confirmed:
        raise SyncError("production 项目 push 必须显式传 --production-confirmed")
    api = api_client(token)
    space, storage_owner = resolve_targets(api, manifest, token)
    api.space_info(space, token=token)

    present_optional_secrets = configured_optional_secrets(env_values, optional_secrets)
    pushed_secrets = secrets | present_optional_secrets
    pushed_remote_secrets = remote_setting_names(manifest, pushed_secrets)
    remote_variables_expected = remote_setting_names(manifest, variables)
    if not prune:
        remote_without_local_values = space_secret_names(space, token) - pushed_remote_secrets
        if remote_without_local_values:
            raise SyncError(
                "远端 Secret 缺少本地明文值，未执行任何写操作；"
                "请先补入 manifest/env，或显式使用 --prune --yes 删除；"
                f"仅列出键名：{sorted(remote_without_local_values)}"
            )
    reconcile_visibility(api, manifest, space, storage_owner, token)
    for name in sorted(pushed_secrets):
        remote_name = remote_setting_name(manifest, name)
        api.add_space_secret(space, remote_name, env_values[name], token=token)
        print(f"secret 已推送：{remote_name}")
    for name in sorted(variables):
        remote_name = remote_setting_name(manifest, name)
        api.add_space_variable(space, remote_name, env_values[name], token=token)
        print(f"variable 已推送：{remote_name}")

    if local_seed is not None:
        destination = seed_uri(storage_owner, manifest, local_seed)
        uploaded, _ = bucket_cp(str(local_seed), destination, token)
        if not uploaded:
            raise SyncError(f"种子上传失败：{destination}")
        verify_seed_round_trip(local_seed, destination, token)
        print(f"种子上传和读回通过：{destination}")
    else:
        print("未配置 seed_file，不推送种子")

    if prune:
        remote_secrets = space_secret_names(space, token)
        remote_variables = api.get_space_variables(space, token=token)
        for name in sorted(remote_secrets - pushed_remote_secrets):
            api.delete_space_secret(space, name, token=token)
            print(f"secret 已删除：{name}")
        for name in sorted(set(remote_variables) - remote_variables_expected):
            api.delete_space_variable(space, name, token=token)
            print(f"variable 已删除：{name}")

    remote_secrets = space_secret_names(space, token)
    remote_variables = api.get_space_variables(space, token=token)
    visibility_findings = visibility_drift(api, manifest, space, storage_owner, token)
    missing_names = (pushed_remote_secrets - remote_secrets) | (
        remote_variables_expected - set(remote_variables)
    )
    value_drift = {
        remote_setting_name(manifest, name)
        for name in variables
        if remote_setting_name(manifest, name) in remote_variables
        and remote_variables[remote_setting_name(manifest, name)].value != env_values[name]
    }
    secret_extras = remote_secrets - pushed_remote_secrets
    variable_extras = set()
    if prune:
        variable_extras = set(remote_variables) - remote_variables_expected
    if missing_names or value_drift or secret_extras or variable_extras or visibility_findings:
        raise SyncError(
            "读回校验失败："
            f"缺少名称 {sorted(missing_names)}；"
            f"variable 值不一致 {sorted(value_drift)}；"
            f"无本地明文值的 secret {sorted(secret_extras)}；"
            f"prune 后多余 variable {sorted(variable_extras)}；"
            f"visibility 不一致 {visibility_findings}"
        )
    print(
        "读回校验通过（Space=protected，bucket=private，"
        "secret 比名称，variable 比值，种子比内容）"
    )
    return 0


def ensure_contained(root: Path, path: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise SyncError(f"pull 目录不能逃逸项目根：{path.name}") from exc


def directory_open_flags() -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return flags


def validate_open_directory(root: Path, path: Path, descriptor: int) -> None:
    try:
        path_mode = path.lstat().st_mode
        path_stat = path.stat(follow_symlinks=False)
    except FileNotFoundError as exc:
        raise SyncError(f"pull 路径组件在校验期间消失：{path.name}") from exc
    if stat.S_ISLNK(path_mode):
        raise SyncError(f"pull 路径组件不能是符号链接：{path.name}")
    if not stat.S_ISDIR(path_mode):
        raise SyncError(f"pull 路径组件必须是目录：{path.name}")
    descriptor_stat = os.fstat(descriptor)
    if not stat.S_ISDIR(descriptor_stat.st_mode):
        raise SyncError(f"pull 路径组件必须是目录：{path.name}")
    if (path_stat.st_dev, path_stat.st_ino) != (
        descriptor_stat.st_dev,
        descriptor_stat.st_ino,
    ):
        raise SyncError(f"pull 路径组件在校验期间被替换：{path.name}")
    ensure_contained(root, path)
    os.fchmod(descriptor, 0o700)


def open_private_directory(root: Path, path: Path) -> int:
    try:
        descriptor = os.open(path, directory_open_flags())
    except OSError as exc:
        raise SyncError(f"pull 路径组件无法安全打开为目录：{path.name}") from exc
    try:
        validate_open_directory(root, path, descriptor)
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def ensure_private_directory(root: Path, path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        ensure_contained(root, path)
        try:
            path.mkdir(mode=0o700, parents=False, exist_ok=False)
        except FileExistsError:
            pass
        mode = path.lstat().st_mode
    if stat.S_ISLNK(mode):
        raise SyncError(f"pull 路径组件不能是符号链接：{path.name}")
    if not stat.S_ISDIR(mode):
        raise SyncError(f"pull 路径组件必须是目录：{path.name}")

    descriptor = open_private_directory(root, path)
    try:
        validate_open_directory(root, path, descriptor)
    finally:
        os.close(descriptor)


def unique_pull_dir(root: Path, space: str) -> Path:
    root = root.resolve()
    if not root.is_dir():
        raise SyncError(f"项目根必须是目录：{root}")
    space_slug = validate_slug(space.split("/", 1)[-1], "Space slug")
    local_root = root / "local"
    archive_root = local_root / "hfs-sync-pulled"
    base = archive_root / space_slug
    for path in (local_root, archive_root, base):
        ensure_private_directory(root, path)
    timestamp = time.strftime("%Y%m%d%H%M%S")
    base_descriptor = open_private_directory(root, base)
    try:
        for attempt in range(256):
            name = timestamp if attempt == 0 else f"{timestamp}-{time.time_ns()}-{attempt - 1}"
            try:
                os.mkdir(name, mode=0o700, dir_fd=base_descriptor)
            except FileExistsError:
                try:
                    existing_mode = os.stat(
                        name,
                        dir_fd=base_descriptor,
                        follow_symlinks=False,
                    ).st_mode
                except OSError as exc:
                    raise SyncError(f"pull 唯一目录碰撞后无法安全检查：{name}") from exc
                if stat.S_ISLNK(existing_mode):
                    raise SyncError(f"pull 路径组件不能是符号链接：{name}")
                if not stat.S_ISDIR(existing_mode):
                    raise SyncError(f"pull 路径组件必须是目录：{name}")
                continue
            except OSError as exc:
                raise SyncError(f"无法创建私有 pull 目录：{name}") from exc

            candidate = base / name
            try:
                candidate_descriptor = os.open(
                    name,
                    directory_open_flags(),
                    dir_fd=base_descriptor,
                )
            except OSError as exc:
                raise SyncError(f"新建 pull 目录无法安全打开：{name}") from exc
            try:
                validate_open_directory(root, candidate, candidate_descriptor)
            except Exception:
                try:
                    os.rmdir(name, dir_fd=base_descriptor)
                except OSError:
                    pass
                raise
            finally:
                os.close(candidate_descriptor)
            return candidate
    finally:
        os.close(base_descriptor)
    raise SyncError("无法创建唯一的 pull 目录")


def stat_identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def validate_open_directory_at(
    parent_descriptor: int,
    name: str,
    descriptor: int,
) -> None:
    try:
        entry_stat = os.stat(
            name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError as exc:
        raise SyncError("pull staging 在校验期间消失") from exc
    descriptor_stat = os.fstat(descriptor)
    if stat.S_ISLNK(entry_stat.st_mode) or not stat.S_ISDIR(entry_stat.st_mode):
        raise SyncError("pull staging 必须是普通目录")
    if not stat.S_ISDIR(descriptor_stat.st_mode):
        raise SyncError("pull staging 打开结果不是目录")
    if stat_identity(entry_stat) != stat_identity(descriptor_stat):
        raise SyncError("pull staging 在校验期间被替换")
    os.fchmod(descriptor, 0o700)


def create_private_staging_at(parent_descriptor: int) -> tuple[str, int]:
    for _ in range(256):
        name = f".staging-{os.urandom(12).hex()}"
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_descriptor)
        except FileExistsError:
            continue
        except OSError as exc:
            raise SyncError("无法在受信 pull 目录中创建私有 staging") from exc

        try:
            descriptor = os.open(
                name,
                directory_open_flags(),
                dir_fd=parent_descriptor,
            )
        except OSError as exc:
            try:
                os.rmdir(name, dir_fd=parent_descriptor)
            except OSError:
                pass
            raise SyncError("pull staging 无法安全打开") from exc
        try:
            validate_open_directory_at(parent_descriptor, name, descriptor)
        except Exception:
            os.close(descriptor)
            try:
                os.rmdir(name, dir_fd=parent_descriptor)
            except OSError:
                pass
            raise
        return name, descriptor
    raise SyncError("无法创建唯一的 pull staging 目录")


def validate_open_regular_file_at(
    directory_descriptor: int,
    filename: str,
    descriptor: int,
) -> None:
    try:
        entry_stat = os.stat(
            filename,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError as exc:
        raise SyncError("实例配置 staging 文件在校验期间消失") from exc
    descriptor_stat = os.fstat(descriptor)
    if stat.S_ISLNK(entry_stat.st_mode) or not stat.S_ISREG(entry_stat.st_mode):
        raise SyncError("实例配置 staging 结果不是普通文件")
    if not stat.S_ISREG(descriptor_stat.st_mode):
        raise SyncError("实例配置 staging 打开结果不是普通文件")
    if stat_identity(entry_stat) != stat_identity(descriptor_stat):
        raise SyncError("实例配置 staging 文件在校验期间被替换")
    os.fchmod(descriptor, 0o600)


def create_private_file_at(
    directory_descriptor: int,
    filename: str,
    content: bytes,
) -> int:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(
            filename,
            flags,
            0o600,
            dir_fd=directory_descriptor,
        )
    except OSError as exc:
        raise SyncError("无法在 pull staging 中创建私有配置文件") from exc
    try:
        validate_open_regular_file_at(directory_descriptor, filename, descriptor)
        remaining = memoryview(content)
        while remaining:
            try:
                written = os.write(descriptor, remaining)
            except InterruptedError:
                continue
            if written <= 0:
                raise SyncError("写入 pull staging 文件失败")
            remaining = remaining[written:]
        os.lseek(descriptor, 0, os.SEEK_SET)
    except Exception:
        os.close(descriptor)
        try:
            os.unlink(filename, dir_fd=directory_descriptor)
        except OSError:
            pass
        raise
    return descriptor


def read_open_file(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        try:
            chunk = os.read(descriptor, 1024 * 1024)
        except InterruptedError:
            continue
        if not chunk:
            break
        chunks.append(chunk)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return b"".join(chunks)


def validate_published_file_at(
    directory_descriptor: int,
    filename: str,
    source_descriptor: int,
) -> None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        published_descriptor = os.open(
            filename,
            flags,
            dir_fd=directory_descriptor,
        )
    except OSError as exc:
        raise SyncError("实例配置回收结果无法安全打开") from exc
    try:
        published_stat = os.fstat(published_descriptor)
        source_stat = os.fstat(source_descriptor)
        if not stat.S_ISREG(published_stat.st_mode):
            raise SyncError("实例配置回收结果不是普通文件")
        if stat_identity(published_stat) != stat_identity(source_stat):
            raise SyncError("实例配置发布结果与受信 staging 文件不一致")
        os.fchmod(published_descriptor, 0o600)
    finally:
        os.close(published_descriptor)


def remove_entry_at(directory_descriptor: int, name: str) -> None:
    try:
        entry_stat = os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return
    if stat.S_ISDIR(entry_stat.st_mode) and not stat.S_ISLNK(entry_stat.st_mode):
        os.rmdir(name, dir_fd=directory_descriptor)
    else:
        os.unlink(name, dir_fd=directory_descriptor)


def cleanup_staging_at(
    parent_descriptor: int,
    staging_name: str,
    staging_descriptor: int,
    filename: str,
) -> None:
    try:
        os.unlink(filename, dir_fd=staging_descriptor)
    except FileNotFoundError:
        pass

    staging_identity = stat_identity(os.fstat(staging_descriptor))
    matching_names: list[str] = []
    # The owned directory may have been renamed; find it by inode without
    # resolving any attacker-controlled path.
    for entry in os.listdir(parent_descriptor):
        try:
            entry_stat = os.stat(
                entry,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            continue
        if stat_identity(entry_stat) == staging_identity:
            matching_names.append(entry)

    for entry in matching_names:
        os.rmdir(entry, dir_fd=parent_descriptor)
    if staging_name not in matching_names:
        remove_entry_at(parent_descriptor, staging_name)
    if not matching_names:
        raise SyncError("pull staging 已被移出受信父目录，无法安全清理")


def cmd_pull(
    root: Path,
    manifest_file: Path = Path("hfs-dev.toml"),
    env_file: Path | None = None,
) -> int:
    root = root.resolve()
    manifest = load_manifest(root, manifest_file)
    validate_manifest(manifest)
    selected_env_file = manifest_env_file(manifest, env_file)
    env_values = load_env(root, selected_env_file)
    token = hf_token(env_values)
    api = api_client(token)
    space, storage_owner = resolve_targets(api, manifest, token)
    api.space_info(space, token=token)
    runtime_uri = instance_uri(manifest, storage_owner)
    if runtime_uri is None:
        raise SyncError("未登记 mount_config_bucket，无法定位实例配置")

    filename = PurePosixPath(str(manifest.get("mount_config_object", "config/config.toml"))).name
    pull_dir = unique_pull_dir(root, space)
    downloaded = pull_dir / filename
    pull_descriptor = open_private_directory(root, pull_dir)
    staging_name: str | None = None
    staging_descriptor: int | None = None
    file_descriptor: int | None = None
    published = False
    sensitive: list[str] = []
    try:
        success, content = bucket_read_bytes(runtime_uri, token)
        if not success:
            raise SyncError(f"实例配置回收失败：{runtime_uri}")
        validate_open_directory(root, pull_dir, pull_descriptor)
        staging_name, staging_descriptor = create_private_staging_at(pull_descriptor)
        file_descriptor = create_private_file_at(
            staging_descriptor,
            filename,
            content,
        )
        staged_content = read_open_file(file_descriptor)
        if staged_content != content:
            raise SyncError("pull staging 内容与 HF CLI 内存输出不一致")
        sensitive = sensitive_seed_text(
            staged_content.decode("utf-8", errors="replace"),
            PurePosixPath(filename).suffix,
            protected_secret_values(env_values, manifest),
        )
        validate_open_directory_at(
            pull_descriptor,
            staging_name,
            staging_descriptor,
        )
        validate_open_regular_file_at(
            staging_descriptor,
            filename,
            file_descriptor,
        )
        if read_open_file(file_descriptor) != content:
            raise SyncError("pull staging 内容在安全检查期间被修改")
        try:
            os.link(
                filename,
                filename,
                src_dir_fd=staging_descriptor,
                dst_dir_fd=pull_descriptor,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            raise SyncError("实例配置回收目标已存在，拒绝覆盖") from exc
        except OSError as exc:
            raise SyncError("实例配置无法安全发布到最终 pull 目录") from exc
        published = True
        validate_published_file_at(
            pull_descriptor,
            filename,
            file_descriptor,
        )
        validate_open_directory(root, pull_dir, pull_descriptor)
    except Exception:
        if published:
            try:
                os.unlink(filename, dir_fd=pull_descriptor)
            except OSError:
                pass
        raise
    finally:
        # A cleanup failure must not replace the security/config error already
        # in flight from validation or parsing.
        primary_exception_active = sys.exc_info()[0] is not None
        cleanup_error: Exception | None = None
        try:
            if file_descriptor is not None:
                try:
                    os.close(file_descriptor)
                except OSError as exc:
                    cleanup_error = exc
            if staging_name is not None and staging_descriptor is not None:
                try:
                    cleanup_staging_at(
                        pull_descriptor,
                        staging_name,
                        staging_descriptor,
                        filename,
                    )
                except Exception as exc:
                    cleanup_error = cleanup_error or exc
            if cleanup_error is not None and not primary_exception_active and published:
                try:
                    os.unlink(filename, dir_fd=pull_descriptor)
                    published = False
                except OSError as exc:
                    cleanup_error = cleanup_error or exc
        finally:
            if staging_descriptor is not None:
                try:
                    os.close(staging_descriptor)
                except OSError as exc:
                    cleanup_error = cleanup_error or exc
            try:
                os.close(pull_descriptor)
            except OSError as exc:
                cleanup_error = cleanup_error or exc
        if cleanup_error is not None and not primary_exception_active:
            raise SyncError("pull staging 清理失败") from cleanup_error
    relative = downloaded.relative_to(root)
    print(f"实例配置已回收：{relative}（来源 {runtime_uri}）")
    if sensitive:
        print(f"WARN：回收配置包含受保护值或敏感字段：{sensitive}")
    print("根种子未修改；请人工 diff、脱密后再手工合并，随后单独执行 push")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["init", "info", "check", "diff", "push", "pull"])
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="项目根目录（默认当前目录）")
    parser.add_argument("--manifest", type=Path, default=Path("hfs-dev.toml"), help="manifest 路径")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="兼容参数；必须与 manifest 的 env_file 完全一致",
    )
    parser.add_argument("--prune", action="store_true", help="push 时删除远端多余设置；默认不删除")
    parser.add_argument("--yes", action="store_true", help="确认执行 --prune 的远端删除")
    parser.add_argument(
        "--production-confirmed",
        action="store_true",
        help="显式确认 production 项目 push；preview 不需要",
    )
    parser.add_argument("--names-only", action="store_true", help="兼容参数；info 永不显示值")
    parser.add_argument("--debug", action="store_true", help="info 额外显示 [compat.env_map]")
    args = parser.parse_args()
    root = args.root.resolve()

    try:
        if args.command == "init":
            if (
                args.env_file is not None
                or args.prune
                or args.yes
                or args.production_confirmed
                or args.names_only
                or args.debug
            ):
                raise SyncError("--env-file/--prune/--yes/--production-confirmed/--names-only/--debug 不适用于 init")
            return cmd_init(root, args.manifest)
        if args.command == "info":
            if args.prune or args.yes or args.production_confirmed:
                raise SyncError("--prune/--yes/--production-confirmed 不适用于 info")
            return cmd_info(
                root,
                args.manifest,
                args.env_file,
                names_only=args.names_only,
                debug=args.debug,
            )
        if args.command == "check":
            if (
                args.env_file is not None
                or args.prune
                or args.yes
                or args.production_confirmed
                or args.names_only
                or args.debug
            ):
                raise SyncError("check 只接受 --root 与 --manifest；其余参数不适用")
            return cmd_check(root, args.manifest)
        if args.command == "diff":
            if args.prune or args.yes or args.production_confirmed or args.names_only or args.debug:
                raise SyncError("--prune/--yes/--production-confirmed/--names-only/--debug 不适用于 diff")
            return cmd_diff(root, args.manifest, args.env_file)
        if args.command == "push":
            if args.names_only or args.debug:
                raise SyncError("--names-only/--debug 只适用于 info")
            return cmd_push(
                root,
                args.prune,
                args.yes,
                args.manifest,
                args.env_file,
                args.production_confirmed,
            )
        if args.prune or args.yes or args.production_confirmed or args.names_only or args.debug:
            raise SyncError("--prune/--yes/--production-confirmed/--names-only/--debug 不适用于 pull")
        return cmd_pull(root, args.manifest, args.env_file)
    except (SyncError, OSError, KeyError, subprocess.SubprocessError) as exc:
        print(f"ERROR：{exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(
            f"ERROR：外部 HF/API 调用失败（{type(exc).__name__}）；响应细节未输出，以免泄露凭据",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
